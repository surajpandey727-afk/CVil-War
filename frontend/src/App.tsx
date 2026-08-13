import { Routes, Route } from 'react-router-dom';

import AppLayout from '@/components/layout/AppLayout';
import Toaster from '@/components/ui/Toaster';
import OfflineBanner from '@/components/ui/OfflineBanner';
import DashboardPage from '@/pages/DashboardPage';
import JobSearchPage from '@/pages/JobSearchPage';
import RunConsolePage from '@/pages/RunConsolePage';
import ApplicationsPage from '@/pages/ApplicationsPage';
import AppDetailPage from '@/pages/AppDetailPage';
import ResumesPage from '@/pages/ResumesPage';
import RoleTargetsPage from '@/pages/RoleTargetsPage';
import SourcesPage from '@/pages/SourcesPage';
import AutomationPage from '@/pages/AutomationPage';
import SettingsPage from '@/pages/SettingsPage';
import AnalyticsPage from '@/pages/AnalyticsPage';
import AdminPage from '@/pages/AdminPage';
import OnboardingPage from '@/pages/OnboardingPage';
import LandingPage from '@/pages/LandingPage';
import LoginPage from '@/pages/LoginPage';
import RegisterPage from '@/pages/RegisterPage';
import ForgotPasswordPage from '@/pages/ForgotPasswordPage';
import ResetPasswordPage from '@/pages/ResetPasswordPage';
import SystemStatePage from '@/pages/SystemStatePage';
import { RequireAuth } from '@/components/auth/RequireAuth';
import { RequireSuperuser } from '@/components/auth/RequireSuperuser';
import { PublicOnly } from '@/components/auth/PublicOnly';

function App() {
  return (
    <>
      <OfflineBanner />

      <Routes>
        <Route path="/" element={<PublicOnly><LandingPage /></PublicOnly>} />
        <Route path="/login" element={<PublicOnly><LoginPage /></PublicOnly>} />
        <Route path="/register" element={<PublicOnly redirectTo="/onboarding"><RegisterPage /></PublicOnly>} />
        <Route path="/forgot-password" element={<PublicOnly><ForgotPasswordPage /></PublicOnly>} />
        {/* Target of the emailed reset link (mailer.build_reset_link → /reset-password?token=…). */}
        <Route path="/reset-password" element={<PublicOnly><ResetPasswordPage /></PublicOnly>} />
        <Route path="/onboarding" element={<RequireAuth><OnboardingPage /></RequireAuth>} />
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/jobs" element={<JobSearchPage />} />
          <Route path="/run" element={<RunConsolePage />} />
          <Route path="/applications" element={<ApplicationsPage />} />
          <Route path="/applications/:id" element={<AppDetailPage />} />
          <Route path="/resumes" element={<ResumesPage />} />
          <Route path="/targets" element={<RoleTargetsPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/automation" element={<AutomationPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/admin" element={<RequireSuperuser><AdminPage /></RequireSuperuser>} />
          <Route path="*" element={<SystemStatePage code="404" />} />
        </Route>
      </Routes>

      <Toaster />
    </>
  );
}

export default App;
