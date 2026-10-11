"""Single-machine durable budget reservations, with a cross-process file lock."""
import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from .errors import ProviderError


class BudgetLedger:
    def __init__(self, path, limit):
        self.path = Path(path)
        self.limit = Decimal(str(limit))
        if not self.limit.is_finite() or self.limit < 0 or self.limit > 200:
            raise ProviderError("config_error", "预算必须在0到200元之间")

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                state = json.loads(self.path.read_text()) if self.path.exists() else {"version": 1, "attempts": []}
                if state.get('version') != 1 or not isinstance(state.get('attempts'), list):
                    raise ValueError('Invalid ledger')
                yield state
                # An interrupted write cannot truncate the previous valid ledger.
                temporary = self.path.with_suffix('.tmp')
                with temporary.open('w') as file:
                    json.dump(state, file, ensure_ascii=False, indent=2)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.path)
            except (ValueError, OSError, KeyError, TypeError):
                raise ProviderError("budget_error", "预算记录无法读取或保存，已停止调用；请检查记录，不要删除后重新计费") from None
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def reserve(self, amount, model, local_request_id, attempt):
        amount = Decimal(str(amount))
        if not amount.is_finite() or amount <= 0:
            raise ProviderError("budget_error", "请求费用估算无效，已停止调用")
        with self.transaction() as state:
            amounts = [Decimal(x['accounted_cny']) for x in state['attempts']]
            if any(not x.is_finite() or x < 0 for x in amounts):
                raise ProviderError("budget_error", "预算记录中的费用无效，已停止调用")
            allocated = sum(amounts, Decimal(0))
            if allocated + amount > self.limit:
                raise ProviderError("budget_exceeded", "剩余预算不足，本次不会发送模型请求")
            reservation = str(uuid.uuid4())
            state['attempts'].append({"id": reservation, "local_request_id": local_request_id,
                                      "model": model, "attempt": attempt, "status": "reserved",
                                      "reserved_cny": str(amount), "accounted_cny": str(amount)})
            return reservation

    def settle(self, reservation, status, amount=None, **metadata):
        with self.transaction() as state:
            entry = next(x for x in state['attempts'] if x['id'] == reservation)
            entry.update(metadata)
            entry['status'] = status
            # Unknown billing (timeout/network/5xx) retains its full reservation.
            if amount is not None:
                entry['accounted_cny'] = str(Decimal(str(amount)))
