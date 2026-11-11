import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
// Base application structure.
import './styles.css'
import './style.css'
import './live-snapshot.css'
// Feature layouts. Keep feature ownership local; visual decisions resolve below.
import './dashboard-enhancements.css'
import './dashboard-redesign.css'
import './business-report.css'
import './project-report-timeline.css'
import './calm-financial-palette.css'
import './financial-operating-room.css'
import './project-portfolio-ledger.css'
import './active-project-age-chart.css'
import './financial-operations-workspace.css'
// Legacy compatibility themes. Canonical tokens and primitives follow last.
import './reference-led-dark.css'
import './hollawall-brand.css'
import './finance-workspace-v2.css'
import './project-lifecycle-market-chart.css'
import './presensi-dashboard.css'
import './design-system.css'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 20_000 } } })

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
