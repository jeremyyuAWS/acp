/**
 * ProcessHealthAlert — four-level alert primitive for platform/process health.
 *
 * Visually and semantically distinct from WCAG accessibility findings. Each alert
 * carries a left border, icon, bold label, title, optional description, and optional
 * action buttons. No data fetching; callers supply all content.
 *
 * Props:
 *   level:        'critical' | 'warning' | 'info' | 'recovered'
 *   title:        string — bold sentence after the label
 *   description?: string — plain-language detail
 *   actions?:     Array<{label: string, onClick: () => void}>
 */

const LEVELS = {
  critical: {
    label: 'CRITICAL',
    icon: '⛔',
    color: 'var(--health-critical-text, #B42318)',
    background: 'var(--health-critical-bg, #FEF3F2)',
    border: 'var(--health-critical-border, #FECDCA)',
    leftBorder: 'var(--health-critical-left, #B42318)',
  },
  warning: {
    label: 'WARNING',
    icon: '⚠',
    color: 'var(--health-warning-text, var(--warn-fg))',
    background: 'var(--health-warning-bg, #FFF7E6)',
    border: 'var(--health-warning-border, #FEDF89)',
    leftBorder: 'var(--health-warning-left, var(--warn-fg))',
  },
  info: {
    label: 'INFORMATION',
    icon: 'ℹ',
    color: 'var(--health-info-text, #175CD3)',
    background: 'var(--health-info-bg, #EFF8FF)',
    border: 'var(--health-info-border, #B2DDFF)',
    leftBorder: 'var(--health-info-left, #175CD3)',
  },
  recovered: {
    label: 'RECOVERED',
    icon: '✓',
    color: 'var(--health-recovered-text, #067647)',
    background: 'var(--health-recovered-bg, #ECFDF3)',
    border: 'var(--health-recovered-border, #ABEFC6)',
    leftBorder: 'var(--health-recovered-left, #067647)',
  },
}

export default function ProcessHealthAlert({ level, title, description, actions }) {
  const config = LEVELS[level] ?? LEVELS.info

  const outerStyle = {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '12px',
    padding: '12px 16px',
    background: config.background,
    border: `1px solid ${config.border}`,
    borderLeft: `4px solid ${config.leftBorder}`,
    borderRadius: '4px',
    color: config.color,
    fontFamily: 'inherit',
  }

  const iconStyle = {
    fontSize: '18px',
    lineHeight: 1,
    flexShrink: 0,
    marginTop: '1px',
  }

  const bodyStyle = {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
    flex: 1,
    minWidth: 0,
  }

  const labelRowStyle = {
    display: 'flex',
    alignItems: 'baseline',
    gap: '8px',
    flexWrap: 'wrap',
  }

  const labelStyle = {
    fontWeight: 700,
    fontSize: '12px',
    letterSpacing: '0.05em',
    lineHeight: 1.4,
  }

  const titleStyle = {
    fontWeight: 700,
    fontSize: '14px',
    lineHeight: 1.4,
  }

  const descriptionStyle = {
    fontWeight: 400,
    fontSize: '14px',
    lineHeight: 1.5,
    color: config.color,
    opacity: 0.85,
  }

  const actionsStyle = {
    display: 'flex',
    gap: '8px',
    flexWrap: 'wrap',
    marginTop: '4px',
  }

  const buttonStyle = {
    border: '1px solid currentColor',
    background: 'transparent',
    color: 'inherit',
    borderRadius: '4px',
    padding: '4px 12px',
    fontSize: '13px',
    fontWeight: 500,
    cursor: 'pointer',
    fontFamily: 'inherit',
    lineHeight: 1.4,
  }

  return (
    <div role="alert" style={outerStyle}>
      <span aria-hidden="true" style={iconStyle}>{config.icon}</span>
      <div style={bodyStyle}>
        <div style={labelRowStyle}>
          <span style={labelStyle}>{config.label}</span>
          <span style={titleStyle}>{title}</span>
        </div>
        {description && (
          <p style={descriptionStyle}>{description}</p>
        )}
        {actions && actions.length > 0 && (
          <div style={actionsStyle}>
            {actions.map(({ label, onClick }, i) => (
              <button key={i} type="button" style={buttonStyle} onClick={onClick}>
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
