import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { getToken } from './lib/api'
import AlertCentre from './pages/alerts/AlertCentre'
import CasePage from './pages/case/CasePage'
import RecordEvent from './pages/case/RecordEvent'
import DistrictDashboard from './pages/dashboard/DistrictDashboard'
import NationalDashboard from './pages/dashboard/NationalDashboard'
import LoginPage from './pages/login/LoginPage'
import ProjectList from './pages/projects/ProjectList'
import ProjectPage from './pages/projects/ProjectPage'
import PublicStatus from './pages/public/PublicStatus'
import ReportsPage from './pages/reports/ReportsPage'
import AdminRulesets from './pages/admin/AdminRulesets'
import AdminIntegrations from './pages/admin/AdminIntegrations'

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!getToken()) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/public" element={<PublicStatus />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/national" replace />} />
        <Route path="/national" element={<NationalDashboard />} />
        <Route path="/projects" element={<ProjectList />} />
        <Route path="/projects/:id" element={<ProjectPage />} />
        <Route path="/cases/:id" element={<CasePage />} />
        <Route path="/cases/:id/record" element={<RecordEvent />} />
        <Route path="/alerts" element={<AlertCentre />} />
        <Route path="/districts/:district" element={<DistrictDashboard />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/admin/rulesets" element={<AdminRulesets />} />
        <Route path="/admin/integrations" element={<AdminIntegrations />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
