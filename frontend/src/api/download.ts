export type DownloadKind = 'MP3' | 'PDF'

// Only the canonical file for the displayed job can be requested.
export async function fetchDownload(jobId: string, kind: DownloadKind, signal: AbortSignal): Promise<{ blob: Blob; filename: string }> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(jobId)) throw new Error('文件编号无效')
  const response = await fetch(`/api/jobs/${jobId}/${kind === 'MP3' ? 'audio' : 'pdf'}?download=true`, { method: 'GET', signal, cache: 'no-store' })
  const expected = kind === 'MP3' ? 'audio/mpeg' : 'application/pdf'
  if (!response.ok || response.headers.get('content-type')?.split(';')[0].trim() !== expected) throw new Error('文件暂时无法下载')
  const blob = await response.blob()
  if (!blob.size) throw new Error('文件暂时无法下载')
  return { blob, filename: `music-${jobId}.${kind.toLowerCase()}` }
}
