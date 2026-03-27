import '../styles/RouteSteps.css';

// ── Step type icons ───────────────────────────────────────────────────────────
const StepIcon = ({ type }) => {
  switch (type) {
    case 'exit':
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          <path d="M16 17l5-5-5-5M21 12H9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      );
    case 'walk':
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="4" r="2" stroke="currentColor" strokeWidth="1.8"/>
          <path d="M9 20l1.5-5L9 12l3 2 2.5-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M7 8.5L9 12M15 8l-1.5 3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
        </svg>
      );
    case 'turn':
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      );
    case 'elevator':
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <rect x="5" y="3" width="14" height="18" rx="2" stroke="currentColor" strokeWidth="1.8"/>
          <path d="M9 10l3-3 3 3M9 14l3 3 3-3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      );
    case 'enter':
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          <path d="M10 17l5-5-5-5M15 12H3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      );
    case 'info':
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8"/>
          <path d="M12 8v1M12 11v5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
        </svg>
      );
    case 'arrive':
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8"/>
          <path d="M8 12l3 3 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      );
    default:
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="4" fill="currentColor"/>
        </svg>
      );
  }
};

// Shown inside the check button (and as the icon when step is completed)
const CheckMark = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <path d="M5 12l5 5L20 7" stroke="currentColor" strokeWidth="2.5"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

// ── Section labels ────────────────────────────────────────────────────────────
const SECTION_LABELS = {
  outdoor: { en: 'Getting there',   ar: 'طريق الوصول',  he: 'דרך ההגעה' },
  indoor:  { en: 'Inside building', ar: 'داخل المبنى',  he: 'בתוך המבנה' },
};

// ── Component ─────────────────────────────────────────────────────────────────
const RouteSteps = ({
  outdoorSteps  = [],
  indoorSteps   = [],
  lang          = 'en',
  isNavigating  = false,
  completedSteps = new Set(),
  activeStep    = 0,
  onStepToggle,
}) => {
  const hasOutdoor = outdoorSteps.length > 0;
  const hasIndoor  = indoorSteps.length > 0;

  if (!hasOutdoor && !hasIndoor) return null;

  const renderList = (steps, offset) =>
    steps.map((step, i) => {
      const globalIndex = offset + i;
      const isCompleted = completedSteps.has(globalIndex);
      const isActive    = isNavigating && globalIndex === activeStep && !isCompleted;
      const isLast      = i === steps.length - 1;

      // Build class string
      let cls = 'rs-step';
      if (isNavigating) {
        if (isCompleted)      cls += ' rs-step--completed';
        else if (isActive)    cls += ' rs-step--active';
        else                  cls += ' rs-step--pending';
      } else if (step.type === 'arrive') {
        cls += ' rs-step--arrive';
      }

      return (
        <div key={i} className={cls}>

          {/* Left column: icon + connector */}
          <div className="rs-step-left">
            <div className={`rs-icon rs-icon--${isCompleted ? 'done' : step.type}`}>
              {isCompleted ? <CheckMark /> : <StepIcon type={step.type} />}
            </div>
            {!isLast && <div className="rs-connector" />}
          </div>

          {/* Body: number + text */}
          <div className="rs-step-body">
            <span className={`rs-step-num${isCompleted ? ' rs-step-num--done' : ''}`}>
              {globalIndex + 1}
            </span>
            <p className="rs-step-text">{step.text}</p>
          </div>

          {/* Check button — only visible when navigating */}
          {isNavigating && (
            <button
              type="button"
              className={`rs-check-btn${
                isCompleted  ? ' rs-check-btn--done'    :
                isActive     ? ' rs-check-btn--active'  :
                               ' rs-check-btn--pending'
              }`}
              onClick={() => onStepToggle?.(globalIndex)}
              aria-label={isCompleted ? 'Unmark step' : 'Mark step done'}
            >
              {isCompleted && <CheckMark />}
            </button>
          )}

        </div>
      );
    });

  return (
    <div className="rs-root">
      {hasOutdoor && (
        <div className="rs-section">
          <div className="rs-section-header rs-section-header--outdoor">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L2 20h20L12 2z" fill="currentColor" opacity="0.7"/>
            </svg>
            <span>{SECTION_LABELS.outdoor[lang] ?? SECTION_LABELS.outdoor.en}</span>
          </div>
          {renderList(outdoorSteps, 0)}
        </div>
      )}

      {hasIndoor && (
        <div className="rs-section">
          <div className="rs-section-header rs-section-header--indoor">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="2"/>
              <path d="M9 21V12h6v9" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
            </svg>
            <span>{SECTION_LABELS.indoor[lang] ?? SECTION_LABELS.indoor.en}</span>
          </div>
          {renderList(indoorSteps, outdoorSteps.length)}
        </div>
      )}
    </div>
  );
};

export default RouteSteps;
