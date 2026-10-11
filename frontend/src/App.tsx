import TablatureDiagnostics from './diagnostics/TablatureDiagnostics'
import PrintPage from './diagnostics/PrintPage'
import CreationPage from './pages/CreationPage'
import RegenerationDiagnostics from './diagnostics/RegenerationDiagnostics'

export default function App() {
  if (window.location.pathname === '/diagnostics/regeneration') return <RegenerationDiagnostics />
  if (window.location.pathname === '/diagnostics/print') return <PrintPage />
  return window.location.pathname === '/diagnostics/tablature' ? <TablatureDiagnostics /> : <CreationPage />
}
