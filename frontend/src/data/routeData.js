// ─── Route Data — Rabin Medical Center campus (dummy SVG coordinates) ─────────
//
// Coordinate space: viewBox="0 0 400 225"  (top-left = 0,0)
//
// X = current user location  →  CURRENT_LOCATION  (the bottom roundabout)
// Y = selected destination   →  BUILDING_POSITIONS[buildingId]
//
// The route line is always drawn:  X ──────► Y
// Every building in hospitalData.js must have an entry here so the
// destination marker and route path update correctly when the user picks
// a different building.

// ── X: fixed current-location point ──────────────────────────────────────────
export const CURRENT_LOCATION = { x: 192, y: 213 };   // bottom roundabout

// ── Y: one entry per building id (matches hospitalData.js ids exactly) ────────
export const BUILDING_POSITIONS = {

  // ── Anchor ──
  entrance:        { x: 192, y: 213 },   // alias for CURRENT_LOCATION

  // ── 18 campus buildings ──
  schneider:       { x: 298, y: 58  },
  heart:           { x: 240, y: 85  },
  nuclear:         { x: 180, y: 108 },
  paning:          { x: 175, y: 78  },
  davidoff:        { x: 128, y: 140 },
  maternity:       { x: 228, y: 112 },
  paleg:           { x: 155, y: 132 },
  gur:             { x: 322, y: 108 },
  hospitalization: { x: 238, y: 144 },
  outpatient:      { x: 168, y: 162 },
  surgery:         { x: 284, y: 118 },
  research:        { x: 336, y: 145 },
  children:        { x: 308, y: 82  },
  mri:             { x: 138, y: 110 },
  welfare:         { x: 102, y: 132 },
  logistics:       { x: 52,  y: 178 },
  warehouse:       { x: 58,  y: 148 },
  synagogue:       { x: 340, y: 78  },
};

// ── Routes: polyline from X (192,213) to every Y ──────────────────────────────
// Each `points` array always starts at CURRENT_LOCATION and ends at the
// building position.  Intermediate points create a realistic-looking path.
// `distanceM` and `timeMin` are walking estimates (dummy).

export const ROUTES = {

  'entrance-schneider': {
    points: [
      { x: 192, y: 213 }, { x: 200, y: 192 }, { x: 218, y: 170 },
      { x: 240, y: 145 }, { x: 258, y: 118 }, { x: 276, y: 96  },
      { x: 285, y: 78  }, { x: 298, y: 58  },
    ],
    distanceM: 420, timeMin: 6,
  },

  'entrance-heart': {
    points: [
      { x: 192, y: 213 }, { x: 200, y: 188 }, { x: 210, y: 158 },
      { x: 222, y: 128 }, { x: 232, y: 106 }, { x: 240, y: 85  },
    ],
    distanceM: 310, timeMin: 4,
  },

  'entrance-nuclear': {
    points: [
      { x: 192, y: 213 }, { x: 190, y: 188 }, { x: 186, y: 162 },
      { x: 183, y: 136 }, { x: 180, y: 108 },
    ],
    distanceM: 220, timeMin: 3,
  },

  'entrance-paning': {
    points: [
      { x: 192, y: 213 }, { x: 188, y: 180 }, { x: 183, y: 148 },
      { x: 179, y: 112 }, { x: 175, y: 78  },
    ],
    distanceM: 240, timeMin: 3,
  },

  'entrance-davidoff': {
    points: [
      { x: 192, y: 213 }, { x: 175, y: 198 }, { x: 158, y: 180 },
      { x: 142, y: 162 }, { x: 128, y: 140 },
    ],
    distanceM: 160, timeMin: 2,
  },

  'entrance-maternity': {
    points: [
      { x: 192, y: 213 }, { x: 200, y: 188 }, { x: 210, y: 162 },
      { x: 220, y: 136 }, { x: 228, y: 112 },
    ],
    distanceM: 200, timeMin: 3,
  },

  'entrance-paleg': {
    points: [
      { x: 192, y: 213 }, { x: 180, y: 195 }, { x: 168, y: 172 },
      { x: 160, y: 150 }, { x: 155, y: 132 },
    ],
    distanceM: 165, timeMin: 2,
  },

  'entrance-gur': {
    points: [
      { x: 192, y: 213 }, { x: 210, y: 190 }, { x: 248, y: 162 },
      { x: 284, y: 138 }, { x: 306, y: 122 }, { x: 322, y: 108 },
    ],
    distanceM: 350, timeMin: 5,
  },

  'entrance-hospitalization': {
    points: [
      { x: 192, y: 213 }, { x: 205, y: 194 }, { x: 218, y: 172 },
      { x: 228, y: 158 }, { x: 238, y: 144 },
    ],
    distanceM: 190, timeMin: 3,
  },

  'entrance-outpatient': {
    points: [
      { x: 192, y: 213 }, { x: 182, y: 197 }, { x: 174, y: 180 },
      { x: 168, y: 162 },
    ],
    distanceM: 105, timeMin: 2,
  },

  'entrance-surgery': {
    points: [
      { x: 192, y: 213 }, { x: 214, y: 188 }, { x: 242, y: 162 },
      { x: 264, y: 140 }, { x: 284, y: 118 },
    ],
    distanceM: 295, timeMin: 4,
  },

  'entrance-research': {
    points: [
      { x: 192, y: 213 }, { x: 218, y: 202 }, { x: 262, y: 182 },
      { x: 300, y: 164 }, { x: 322, y: 155 }, { x: 336, y: 145 },
    ],
    distanceM: 365, timeMin: 5,
  },

  'entrance-children': {
    points: [
      { x: 192, y: 213 }, { x: 210, y: 185 }, { x: 242, y: 155 },
      { x: 272, y: 122 }, { x: 294, y: 100 }, { x: 308, y: 82  },
    ],
    distanceM: 375, timeMin: 5,
  },

  'entrance-mri': {
    points: [
      { x: 192, y: 213 }, { x: 178, y: 190 }, { x: 165, y: 162 },
      { x: 150, y: 136 }, { x: 138, y: 110 },
    ],
    distanceM: 240, timeMin: 3,
  },

  'entrance-welfare': {
    points: [
      { x: 192, y: 213 }, { x: 165, y: 204 }, { x: 140, y: 180 },
      { x: 118, y: 158 }, { x: 102, y: 132 },
    ],
    distanceM: 225, timeMin: 3,
  },

  'entrance-logistics': {
    points: [
      { x: 192, y: 213 }, { x: 145, y: 214 }, { x: 96,  y: 210 },
      { x: 66,  y: 196 }, { x: 52,  y: 178 },
    ],
    distanceM: 200, timeMin: 3,
  },

  'entrance-warehouse': {
    points: [
      { x: 192, y: 213 }, { x: 148, y: 214 }, { x: 100, y: 208 },
      { x: 74,  y: 182 }, { x: 58,  y: 148 },
    ],
    distanceM: 235, timeMin: 3,
  },

  'entrance-synagogue': {
    points: [
      { x: 192, y: 213 }, { x: 210, y: 188 }, { x: 238, y: 158 },
      { x: 268, y: 122 }, { x: 300, y: 96  },
      { x: 322, y: 78  }, { x: 340, y: 78  },
    ],
    distanceM: 380, timeMin: 5,
  },
};

// ── Step-by-step outdoor directions (en / ar / he) ────────────────────────────
// Buildings with specific step lists; all others use GENERIC_STEPS below.

export const ROUTE_STEPS = {

  'entrance-schneider': {
    en: [
      { type: 'exit',  text: 'Start at the main roundabout entrance' },
      { type: 'walk',  text: 'Walk north-east along the campus road' },
      { type: 'turn',  text: 'Bear right past the central plaza' },
      { type: 'walk',  text: 'Continue uphill toward the northern buildings' },
      { type: 'walk',  text: 'Pass the Heart Center on your left' },
      { type: 'enter', text: "Enter Schneider Children's Medical Center" },
    ],
    ar: [
      { type: 'exit',  text: 'ابدأ من مدخل الدوار الرئيسي' },
      { type: 'walk',  text: 'سر شمال شرقاً على طريق الحرم الجامعي' },
      { type: 'turn',  text: 'اتجه يميناً بجانب الساحة المركزية' },
      { type: 'walk',  text: 'تابع المسير نحو المباني الشمالية' },
      { type: 'walk',  text: 'مرّ بجانب مركز القلب على يسارك' },
      { type: 'enter', text: 'ادخل إلى مركز شنايدر الطبي للأطفال' },
    ],
    he: [
      { type: 'exit',  text: 'התחל בכיכר הכניסה הראשית' },
      { type: 'walk',  text: 'לך צפון-מזרחה לאורך דרך הקמפוס' },
      { type: 'turn',  text: 'פנה ימינה ליד הכיכר המרכזית' },
      { type: 'walk',  text: 'המשך במעלה לכיוון המבנים הצפוניים' },
      { type: 'walk',  text: 'עבור ליד מרכז הלב משמאלך' },
      { type: 'enter', text: 'כנס למרכז שניידר לרפואת ילדים' },
    ],
  },

  'entrance-heart': {
    en: [
      { type: 'exit',  text: 'Start at the main roundabout entrance' },
      { type: 'walk',  text: 'Walk north along the central campus path' },
      { type: 'turn',  text: 'Follow the blue Cardiology signs right' },
      { type: 'enter', text: 'Enter the Heart Center (מרכז הלב)' },
    ],
    ar: [
      { type: 'exit',  text: 'ابدأ من مدخل الدوار الرئيسي' },
      { type: 'walk',  text: 'سر شمالاً على الممر المركزي' },
      { type: 'turn',  text: 'اتبع لافتات قسم القلب الزرقاء إلى اليمين' },
      { type: 'enter', text: 'ادخل إلى مركز القلب' },
    ],
    he: [
      { type: 'exit',  text: 'התחל בכיכר הכניסה הראשית' },
      { type: 'walk',  text: 'לך צפונה לאורך השביל המרכזי' },
      { type: 'turn',  text: 'עקוב אחרי שלטי קרדיולוגיה כחולים ימינה' },
      { type: 'enter', text: 'כנס למרכז הלב' },
    ],
  },

  'entrance-davidoff': {
    en: [
      { type: 'exit',  text: 'Start at the main roundabout' },
      { type: 'walk',  text: 'Walk north-west along the side path (~160 m)' },
      { type: 'enter', text: 'Enter Davidoff Cancer Center' },
    ],
    ar: [
      { type: 'exit',  text: 'ابدأ من الدوار الرئيسي' },
      { type: 'walk',  text: 'سر شمال غرب على المسار الجانبي (~١٦٠م)' },
      { type: 'enter', text: 'ادخل إلى مركز دافيدوف للسرطان' },
    ],
    he: [
      { type: 'exit',  text: 'התחל בכיכר הראשית' },
      { type: 'walk',  text: 'לך צפון-מערבה לאורך השביל הצדדי (~160 מ׳)' },
      { type: 'enter', text: 'כנס למרכז דוידוף לסרטן' },
    ],
  },
};

// ── Generic fallback directions (any building without a specific entry) ────────
export const GENERIC_STEPS = {
  en: (buildingName) => [
    { type: 'exit',  text: 'Start at the main roundabout entrance (X)' },
    { type: 'walk',  text: 'Follow the campus signs toward your destination' },
    { type: 'enter', text: `Enter ${buildingName}` },
  ],
  ar: (buildingName) => [
    { type: 'exit',  text: 'ابدأ من مدخل الدوار الرئيسي (X)' },
    { type: 'walk',  text: 'اتبع لافتات الحرم الجامعي نحو وجهتك' },
    { type: 'enter', text: `ادخل إلى ${buildingName}` },
  ],
  he: (buildingName) => [
    { type: 'exit',  text: 'התחל בכיכר הכניסה הראשית (X)' },
    { type: 'walk',  text: 'עקוב אחרי שלטי הקמפוס לכיוון היעד' },
    { type: 'enter', text: `כנס אל ${buildingName}` },
  ],
};

// ── Indoor steps per floor (appended after outdoor route) ─────────────────────
export const INDOOR_STEPS = {
  en: (roomName, floor) => {
    const steps = [{ type: 'info', text: 'You are now inside the building' }];
    if (floor > 0)      steps.push({ type: 'elevator', text: `Take the elevator to floor ${floor}` });
    else if (floor < 0) steps.push({ type: 'elevator', text: `Take the elevator down to basement ${Math.abs(floor)}` });
    else                steps.push({ type: 'walk',     text: 'Stay on the ground floor' });
    steps.push({ type: 'arrive', text: `Arrive at ${roomName}` });
    return steps;
  },
  ar: (roomName, floor) => {
    const steps = [{ type: 'info', text: 'أنت الآن داخل المبنى' }];
    if (floor > 0)      steps.push({ type: 'elevator', text: `اصعد بالمصعد إلى الطابق ${floor}` });
    else if (floor < 0) steps.push({ type: 'elevator', text: `انزل بالمصعد إلى الطابق السفلي ${Math.abs(floor)}` });
    else                steps.push({ type: 'walk',     text: 'ابقَ في الطابق الأرضي' });
    steps.push({ type: 'arrive', text: `وصلت إلى ${roomName}` });
    return steps;
  },
  he: (roomName, floor) => {
    const steps = [{ type: 'info', text: 'אתה נמצא עכשיו בתוך המבנה' }];
    if (floor > 0)      steps.push({ type: 'elevator', text: `קח את המעלית לקומה ${floor}` });
    else if (floor < 0) steps.push({ type: 'elevator', text: `רד במעלית לקומת מרתף ${Math.abs(floor)}` });
    else                steps.push({ type: 'walk',     text: 'הישאר בקומת הקרקע' });
    steps.push({ type: 'arrive', text: `הגעת אל ${roomName}` });
    return steps;
  },
};
