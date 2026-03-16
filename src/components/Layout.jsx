import React from 'react';
import QuickRouteLogo from './QuickRouteLogo';
import '../styles/layout.css';

const Layout = ({ children, screenNumber, pageTitle }) => {
  return (
    <div className="layout-wrapper">
      <div className="layout-shell">

        {/* Screen number badge */}
        {screenNumber && (
          <div className="screen-badge">
            {String(screenNumber).padStart(2, '0')} / 30
          </div>
        )}

        {/* Header with logo */}
        <header className="layout-header">
          <div className="logo-container">
            <div className="logo-icon-wrap">
              <QuickRouteLogo size={42} />
            </div>
            <div className="logo-wordmark">
              Quick<span>Route</span>
            </div>
          </div>
          <div className="layout-divider" />
          {pageTitle && (
            <p className="page-label">{pageTitle}</p>
          )}
        </header>

        {/* Main content */}
        <main className="layout-content">
          {children || <div className="content-placeholder" />}
        </main>

        {/* Bottom nav placeholder */}
        <div className="bottom-nav-placeholder">
          <div className="bottom-nav-dots">
            <span /><span /><span /><span /><span />
          </div>
        </div>

      </div>
    </div>
  );
};

export default Layout;
