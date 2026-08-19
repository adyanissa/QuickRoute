import { useEffect, useMemo, useRef, useState } from 'react';
import AdminScreenHeader from '../components/dashboard/AdminScreenHeader';
import { useNavigate, useLocation } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { useAdmin } from '../context/AdminContext';
import { getLocalizedText } from '../utils/localization';
import { getMaps, buildMapAssetUrl, suggestDestinationName } from '../api/mapsApi';
import { getRoutePoints } from '../api/routePointsApi';
import { getRouteEdges } from '../api/routeEdgesApi';
import {
  computeOriginalImageCoords,
  summarizeOcrSuggestion,
  applySuggestedName,
} from '../utils/destinationPlacement';
import {
  formatFloorDisplay,
  sortFloorsByNumber,
  resolveMapReferenceStatus,
} from '../utils/mapGroupHelpers';
import {
  DESTINATION_TYPE_GROUP_KEYS,
  DESTINATION_TYPE_GROUPS,
} from '../constants/destinationTypes';
import {
  buildDestinationTypeSelectGroups,
  resolveDestinationTypeLabel,
} from '../utils/destinationTypeHelpers';
import {
  saveRoomDraft,
  loadAndClearRoomDraft,
} from '../utils/roomDraftStorage';
import {
  UNGROUPED_MAP_GROUP_KEY,
  buildRoomMapGroupOptions,
  floorMapsForGroup,
  resolveAutoSelectedMapGroupKey,
  resolveAutoSelectedFloorMapId,
  buildFloorMapOptionLabel,
} from '../utils/roomMapSelectionHelpers';
import '../styles/adminScreens.css';

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const UI = {
  en: {
    title: 'Rooms & Destinations',
    back: 'Back',
    selectBuilding: 'Select Building',
    allBuildings: 'All',
    addBtn: 'Add Room',
    addTitle: 'Add Room / Destination',
    editTitle: 'Edit Room / Destination',
    section: 'Rooms',
    fields: {
      name: 'Room Name (EN)', nameAr: 'Room Name (AR)', nameHe: 'Room Name (HE)', type: 'Type',
      floor: 'Floor', description: 'Description',
    },
    emptyTranslation: 'No translation yet',
    save: 'Save', cancel: 'Cancel',
    confirmDelete: 'Delete this room?',
    yes: 'Yes, Delete',
    empty: 'No rooms found',
    emptyHint: 'Tap "Add Room" to create one',
    count: (n) => `${n} room${n !== 1 ? 's' : ''}`,
    floor: 'Floor',
    loading: 'Loading rooms...',
    noBuildings: 'No buildings found',
    noBuildingsHint: 'Add a building first, then add rooms to it',
    saveError: 'Failed to save room',
    deleteError: 'Failed to delete room',

    modeMap: 'Select on Map',
    modeManual: 'Manual Entry',
    selectMap: 'Map',
    selectMapPlaceholder: 'Choose a map…',
    noMapsForBuilding: 'No maps uploaded for this building yet',
    clickMapHint: 'Click the real room/store location on the map below',
    loadingMap: 'Loading map…',
    clearMarker: 'Clear marker',
    markerSet: 'Location selected',
    markerNotSet: 'No location selected yet',
    suggestName: 'Suggest Name from Map',
    suggestingName: 'Reading map text…',
    useThisName: 'Use this name',
    ocrLowConfidence: 'Low confidence — please verify before using it.',
    ocrUnavailableHint: 'You can still type the name manually below.',
    connectionStatus: 'Graph connection',
    connected: 'Connected to walkable graph',
    notConnected: 'No valid graph connection found — connect it manually in Map Management',
    routePointCreated: 'New destination point created',
    routePointReused: 'Reused an existing point at this location',
    savePlacementError: 'Select a map and click a location before saving',
    saveSummaryTitle: 'Destination saved',
    saveSummaryPoint: (reused) => reused
      ? 'Route point: reused existing point'
      : 'Route point: created new point',
    saveSummaryConnection: (connected) => connected
      ? 'Graph connection: connected'
      : 'Graph connection: not connected (connect manually if needed)',
    saveSummaryOcr: (used) => used
      ? 'Name source: OCR suggestion'
      : 'Name source: entered manually',
    legacyMapWarning: 'This destination is linked to a legacy map and requires reassignment.',
    legacyMapReassign: 'Select the correct current floor map below, then click a location on it and Save.',

    // Part 3 — Building -> Map Group -> Floor Map hierarchy.
    selectMapGroup: 'Map Group',
    selectMapGroupPlaceholder: 'Select Map Group…',
    selectFloorMap: 'Floor Map',
    selectFloorMapPlaceholder: 'Select Floor Map…',

    // Part 4 — Add/Upload New Map action.
    addUploadMap: 'Add / Upload New Map',

    // Part 6 — empty/loading/error states.
    loadingMaps: 'Loading maps…',
    noMapsConfigured: 'No maps are configured for this building yet.',
    mapsLoadError: 'Maps could not be loaded.',
    retryMaps: 'Retry',

    // Part 7 — real graph-connection states (never an invented success).
    graphReviewRequired: 'Destination saved, but graph connection requires admin review',
    graphInvalidMap: 'Invalid Map',
    graphNoWalkableGraph: 'No walkable graph exists on this floor',

    // Part 2/8 — grouped Type selector labels.
    typeGroupLabels: {
      general: 'General',
      medical: 'Medical',
      retail: 'Retail & Food',
      public: 'Public Facilities',
      navigation: 'Access & Navigation',
      education: 'Education',
      legacy: 'Legacy',
    },
    typeLabels: {
      room: 'Room', office: 'Office', reception: 'Reception', waiting_area: 'Waiting Area',
      information_desk: 'Information Desk', service: 'Service', other: 'Other',
      emergency: 'Emergency', clinic: 'Clinic', lab: 'Lab', imaging: 'Imaging', pharmacy: 'Pharmacy',
      operating_room: 'Operating Room', treatment_room: 'Treatment Room',
      examination_room: 'Examination Room', nurses_station: "Nurses' Station",
      store: 'Store', supermarket: 'Supermarket', convenience_store: 'Convenience Store',
      clothing_store: 'Clothing Store', electronics_store: 'Electronics Store', bookstore: 'Bookstore',
      restaurant: 'Restaurant', cafe: 'Café', bakery: 'Bakery', food_court: 'Food Court',
      kiosk: 'Kiosk', bank: 'Bank', atm: 'ATM',
      restroom: 'Restroom', accessible_restroom: 'Accessible Restroom', prayer_room: 'Prayer Room',
      childcare: 'Childcare', security: 'Security', customer_service: 'Customer Service',
      ticket_office: 'Ticket Office',
      entrance: 'Entrance', exit: 'Exit', parking: 'Parking', pickup_point: 'Pickup Point',
      classroom: 'Classroom', lecture_hall: 'Lecture Hall', library: 'Library',
      computer_lab: 'Computer Lab', administration: 'Administration',
      operating: 'Operating (Legacy)',
    },
  },
  ar: {
    title: 'الغرف والوجهات',
    back: 'رجوع',
    selectBuilding: 'اختر المبنى',
    allBuildings: 'الكل',
    addBtn: 'إضافة غرفة',
    addTitle: 'إضافة غرفة / وجهة',
    editTitle: 'تعديل غرفة / وجهة',
    section: 'الغرف',
    fields: {
      name: 'اسم الغرفة (EN)', nameAr: 'اسم الغرفة (AR)', nameHe: 'اسم الغرفة (HE)',
      type: 'النوع', floor: 'الطابق', description: 'الوصف',
    },
    emptyTranslation: 'لا توجد ترجمة بعد',
    save: 'حفظ', cancel: 'إلغاء',
    confirmDelete: 'حذف هذه الغرفة؟',
    yes: 'نعم، احذف',
    empty: 'لا توجد غرف',
    emptyHint: 'اضغط "إضافة غرفة" للإنشاء',
    count: (n) => `${n} غرفة`,
    floor: 'طابق',
    loading: 'جاري تحميل الغرف...',
    noBuildings: 'لا توجد مباني',
    noBuildingsHint: 'أضف مبنى أولاً، ثم أضف غرفاً إليه',
    saveError: 'فشل حفظ الغرفة',
    deleteError: 'فشل حذف الغرفة',

    modeMap: 'اختيار من الخريطة',
    modeManual: 'إدخال يدوي',
    selectMap: 'الخريطة',
    selectMapPlaceholder: 'اختر خريطة…',
    noMapsForBuilding: 'لا توجد خرائط مرفوعة لهذا المبنى بعد',
    clickMapHint: 'انقر على موقع الغرفة/المتجر الحقيقي على الخريطة أدناه',
    loadingMap: 'جاري تحميل الخريطة…',
    clearMarker: 'مسح العلامة',
    markerSet: 'تم تحديد الموقع',
    markerNotSet: 'لم يتم تحديد موقع بعد',
    suggestName: 'اقترح اسمًا من الخريطة',
    suggestingName: 'جاري قراءة نص الخريطة…',
    useThisName: 'استخدم هذا الاسم',
    ocrLowConfidence: 'ثقة منخفضة — يرجى التحقق قبل الاستخدام.',
    ocrUnavailableHint: 'لا يزال بإمكانك كتابة الاسم يدويًا أدناه.',
    connectionStatus: 'اتصال الشبكة',
    connected: 'متصل بشبكة المسارات',
    notConnected: 'لم يتم العثور على اتصال صالح — قم بالتوصيل يدويًا في إدارة الخريطة',
    routePointCreated: 'تم إنشاء نقطة وجهة جديدة',
    routePointReused: 'تمت إعادة استخدام نقطة موجودة في هذا الموقع',
    savePlacementError: 'اختر خريطة وانقر على موقع قبل الحفظ',
    saveSummaryTitle: 'تم حفظ الوجهة',
    saveSummaryPoint: (reused) => reused
      ? 'نقطة المسار: إعادة استخدام نقطة موجودة'
      : 'نقطة المسار: تم إنشاء نقطة جديدة',
    saveSummaryConnection: (connected) => connected
      ? 'اتصال الشبكة: متصل'
      : 'اتصال الشبكة: غير متصل (قم بالتوصيل يدويًا إذا لزم الأمر)',
    saveSummaryOcr: (used) => used
      ? 'مصدر الاسم: اقتراح OCR'
      : 'مصدر الاسم: تم الإدخال يدويًا',
    legacyMapWarning: 'هذه الوجهة مرتبطة بخريطة قديمة وتحتاج إلى إعادة تعيين.',
    legacyMapReassign: 'اختر خريطة الطابق الصحيحة الحالية أدناه، ثم انقر على موقع عليها واحفظ.',

    selectMapGroup: 'مجموعة الخرائط',
    selectMapGroupPlaceholder: 'اختر مجموعة الخرائط…',
    selectFloorMap: 'خريطة الطابق',
    selectFloorMapPlaceholder: 'اختر خريطة الطابق…',

    addUploadMap: 'إضافة / رفع خريطة جديدة',

    loadingMaps: 'جاري تحميل الخرائط…',
    noMapsConfigured: 'لا توجد خرائط مُعدة لهذا المبنى بعد.',
    mapsLoadError: 'تعذر تحميل الخرائط.',
    retryMaps: 'إعادة المحاولة',

    graphReviewRequired: 'تم حفظ الوجهة، لكن اتصال الشبكة يحتاج إلى مراجعة الإدارة',
    graphInvalidMap: 'خريطة غير صالحة',
    graphNoWalkableGraph: 'لا توجد شبكة مسارات على هذا الطابق',

    typeGroupLabels: {
      general: 'عام',
      medical: 'طبي',
      retail: 'تجزئة ومطاعم',
      public: 'مرافق عامة',
      navigation: 'الوصول والتنقل',
      education: 'تعليم',
      legacy: 'قديم',
    },
    typeLabels: {
      room: 'غرفة', office: 'مكتب', reception: 'استقبال', waiting_area: 'منطقة الانتظار',
      information_desk: 'مكتب المعلومات', service: 'خدمة', other: 'أخرى',
      emergency: 'طوارئ', clinic: 'عيادة', lab: 'مختبر', imaging: 'أشعة', pharmacy: 'صيدلية',
      operating_room: 'غرفة العمليات', treatment_room: 'غرفة العلاج',
      examination_room: 'غرفة الفحص', nurses_station: 'محطة التمريض',
      store: 'متجر', supermarket: 'سوبر ماركت', convenience_store: 'متجر بقالة',
      clothing_store: 'متجر ملابس', electronics_store: 'متجر إلكترونيات', bookstore: 'مكتبة كتب',
      restaurant: 'مطعم', cafe: 'مقهى', bakery: 'مخبز', food_court: 'ساحة الطعام',
      kiosk: 'كشك', bank: 'بنك', atm: 'صراف آلي',
      restroom: 'دورة مياه', accessible_restroom: 'دورة مياه لذوي الإعاقة', prayer_room: 'غرفة صلاة',
      childcare: 'رعاية الأطفال', security: 'الأمن', customer_service: 'خدمة العملاء',
      ticket_office: 'مكتب التذاكر',
      entrance: 'مدخل', exit: 'مخرج', parking: 'موقف سيارات', pickup_point: 'نقطة استلام',
      classroom: 'قاعة دراسية', lecture_hall: 'قاعة محاضرات', library: 'مكتبة',
      computer_lab: 'معمل حاسوب', administration: 'الإدارة',
      operating: 'عمليات (قديم)',
    },
  },
  he: {
    title: 'חדרים ויעדים',
    back: 'חזרה',
    selectBuilding: 'בחר מבנה',
    allBuildings: 'הכל',
    addBtn: 'הוסף חדר',
    addTitle: 'הוסף חדר / יעד',
    editTitle: 'ערוך חדר / יעד',
    section: 'חדרים',
    fields: {
      name: 'שם חדר (EN)', nameAr: 'שם חדר (AR)', nameHe: 'שם חדר (HE)',
      type: 'סוג', floor: 'קומה', description: 'תיאור',
    },
    emptyTranslation: 'אין תרגום עדיין',
    save: 'שמור', cancel: 'ביטול',
    confirmDelete: 'למחוק חדר זה?',
    yes: 'כן, מחק',
    empty: 'אין חדרים',
    emptyHint: 'לחץ "הוסף חדר" ליצירה',
    count: (n) => `${n} חדרים`,
    floor: 'קומה',
    loading: 'טוען חדרים...',
    noBuildings: 'אין מבנים',
    noBuildingsHint: 'הוסף מבנה תחילה, ואז הוסף לו חדרים',
    saveError: 'שמירת החדר נכשלה',
    deleteError: 'מחיקת החדר נכשלה',

    modeMap: 'בחר על המפה',
    modeManual: 'הזנה ידנית',
    selectMap: 'מפה',
    selectMapPlaceholder: 'בחר מפה…',
    noMapsForBuilding: 'עדיין אין מפות שהועלו למבנה זה',
    clickMapHint: 'לחץ על מיקום החדר/החנות האמיתי במפה למטה',
    loadingMap: 'טוען מפה…',
    clearMarker: 'נקה סימון',
    markerSet: 'המיקום נבחר',
    markerNotSet: 'עדיין לא נבחר מיקום',
    suggestName: 'הצע שם מהמפה',
    suggestingName: 'קורא טקסט מהמפה…',
    useThisName: 'השתמש בשם זה',
    ocrLowConfidence: 'ביטחון נמוך — יש לאמת לפני שימוש.',
    ocrUnavailableHint: 'עדיין ניתן להקליד את השם ידנית למטה.',
    connectionStatus: 'חיבור לרשת',
    connected: 'מחובר לרשת המסלולים',
    notConnected: 'לא נמצא חיבור תקין — חבר ידנית בניהול מפה',
    routePointCreated: 'נוצרה נקודת יעד חדשה',
    routePointReused: 'נעשה שימוש חוזר בנקודה קיימת במיקום זה',
    savePlacementError: 'בחר מפה ולחץ על מיקום לפני השמירה',
    saveSummaryTitle: 'היעד נשמר',
    saveSummaryPoint: (reused) => reused
      ? 'נקודת מסלול: שימוש חוזר בנקודה קיימת'
      : 'נקודת מסלול: נוצרה נקודה חדשה',
    saveSummaryConnection: (connected) => connected
      ? 'חיבור לרשת: מחובר'
      : 'חיבור לרשת: לא מחובר (חבר ידנית אם צריך)',
    saveSummaryOcr: (used) => used
      ? 'מקור השם: הצעת OCR'
      : 'מקור השם: הוזן ידנית',
    legacyMapWarning: 'יעד זה מקושר למפה ישנה ודורש שיוך מחדש.',
    legacyMapReassign: 'בחר את מפת הקומה הנוכחית הנכונה למטה, לחץ על מיקום עליה ושמור.',

    selectMapGroup: 'קבוצת מפות',
    selectMapGroupPlaceholder: 'בחר קבוצת מפות…',
    selectFloorMap: 'מפת קומה',
    selectFloorMapPlaceholder: 'בחר מפת קומה…',

    addUploadMap: 'הוסף / העלה מפה חדשה',

    loadingMaps: 'טוען מפות…',
    noMapsConfigured: 'עדיין לא הוגדרו מפות למבנה זה.',
    mapsLoadError: 'לא ניתן היה לטעון את המפות.',
    retryMaps: 'נסה שוב',

    graphReviewRequired: 'היעד נשמר, אך חיבור הרשת דורש בדיקת מנהל',
    graphInvalidMap: 'מפה לא תקינה',
    graphNoWalkableGraph: 'אין רשת מסלולים בקומה זו',

    typeGroupLabels: {
      general: 'כללי',
      medical: 'רפואי',
      retail: 'קמעונאות ומזון',
      public: 'מתקנים ציבוריים',
      navigation: 'גישה וניווט',
      education: 'חינוך',
      legacy: 'ישן',
    },
    typeLabels: {
      room: 'חדר', office: 'משרד', reception: 'קבלה', waiting_area: 'אזור המתנה',
      information_desk: 'דלפק מידע', service: 'שירות', other: 'אחר',
      emergency: 'חדר מיון', clinic: 'מרפאה', lab: 'מעבדה', imaging: 'הדמיה', pharmacy: 'בית מרקחת',
      operating_room: 'חדר ניתוח', treatment_room: 'חדר טיפולים',
      examination_room: 'חדר בדיקה', nurses_station: 'עמדת אחיות',
      store: 'חנות', supermarket: 'סופרמרקט', convenience_store: 'מינימרקט',
      clothing_store: 'חנות בגדים', electronics_store: 'חנות אלקטרוניקה', bookstore: 'חנות ספרים',
      restaurant: 'מסעדה', cafe: 'בית קפה', bakery: 'מאפייה', food_court: 'אזור מזון',
      kiosk: 'קיוסק', bank: 'בנק', atm: 'כספומט',
      restroom: 'שירותים', accessible_restroom: 'שירותים נגישים', prayer_room: 'חדר תפילה',
      childcare: 'מעון יום', security: 'אבטחה', customer_service: 'שירות לקוחות',
      ticket_office: 'קופת כרטיסים',
      entrance: 'כניסה', exit: 'יציאה', parking: 'חניה', pickup_point: 'נקודת איסוף',
      classroom: 'כיתה', lecture_hall: 'אולם הרצאות', library: 'ספרייה',
      computer_lab: 'מעבדת מחשבים', administration: 'מנהלה',
      operating: 'ניתוחים (ישן)',
    },
  },
};

// Per-GROUP (not per-value) coloring — with 45+ canonical values across
// 6 groups, a per-value color map would be unmaintainable and would fall
// silently back to blue for every new type anyway. A legacy/unrecognized
// value (not in any group) falls back to the same default blue tag.
const GROUP_COLOR = {
  general: 'adm-tag-blue',
  medical: 'adm-tag-red',
  retail: 'adm-tag-green',
  public: 'adm-tag-purple',
  navigation: 'adm-tag-orange',
  education: 'adm-tag-blue',
};

const typeToGroupKey = (value) =>
  DESTINATION_TYPE_GROUP_KEYS.find((groupKey) =>
    DESTINATION_TYPE_GROUPS[groupKey].includes(value),
  );

const BackArrow = ({ flip }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const RoomIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M9 3v18M3 9h6M3 15h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
);

const AddIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <line x1="12" y1="5" x2="12" y2="19" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/>
    <line x1="5" y1="12" x2="19" y2="12" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/>
  </svg>
);

const EditIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const DeleteIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <polyline points="3 6 5 6 21 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const EMPTY_ROOM = {
  id: '', name: '', nameAr: '', nameHe: '', type: 'room', floor: 0, description: '',
  semanticPublicationId: null, semanticEntityExternalId: null, semanticEntityType: null,
  mapId: null, x: null, y: null, routePointId: null,
};

// ── MapDestinationPicker ─────────────────────────────────────────────────────
// Self-contained click-to-place map view: shows the selected map image,
// the existing walkable graph (read-only, faded) for context, and a
// marker at the currently selected destination location. All coordinates
// in/out are original-image pixels (see utils/destinationPlacement.js) —
// never on-screen/display pixels.
const MapDestinationPicker = ({ map, routePoints, routeEdges, marker, onPick, t }) => {
  const imageRef = useRef(null);
  const [metrics, setMetrics] = useState(null);

  const imageUrl = buildMapAssetUrl(
    map?.displayImageUrl || map?.sourceImageUrl || map?.imageUrl
  );

  const syncMetrics = () => {
    const image = imageRef.current;
    if (!image?.naturalWidth || !image?.naturalHeight) return;
    setMetrics({
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
    });
  };

  useEffect(() => {
    const handleResize = () => syncMetrics();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleClick = (event) => {
    const image = event.currentTarget;
    const rect = image.getBoundingClientRect();

    const coords = computeOriginalImageCoords({
      clientX: event.clientX,
      clientY: event.clientY,
      rectLeft: rect.left,
      rectTop: rect.top,
      rectWidth: rect.width,
      rectHeight: rect.height,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
    });

    if (coords) onPick(coords.x, coords.y);
  };

  if (!imageUrl) {
    return (
      <div className="adm-map-picker-empty">{t.loadingMap}</div>
    );
  }

  return (
    <div className="adm-map-picker">
      <img
        ref={imageRef}
        src={imageUrl}
        alt={map?.title || 'Map'}
        className="adm-map-picker-img"
        draggable="false"
        onLoad={syncMetrics}
        onClick={handleClick}
      />

      {metrics && (
        <svg
          className="adm-map-picker-svg"
          viewBox={`0 0 ${metrics.naturalWidth} ${metrics.naturalHeight}`}
          preserveAspectRatio="xMidYMid meet"
        >
          {routeEdges.map((edge) => {
            const from = routePoints.find((p) => p.id === edge.from_point_id);
            const to = routePoints.find((p) => p.id === edge.to_point_id);
            if (!from || !to) return null;
            return (
              <line
                key={edge.id}
                x1={from.x} y1={from.y} x2={to.x} y2={to.y}
                stroke="#8aaacb" strokeWidth={Math.max(2, metrics.naturalWidth * 0.0012)}
                strokeLinecap="round" opacity="0.55"
              />
            );
          })}

          {routePoints.map((point) => (
            <circle
              key={point.id}
              cx={point.x} cy={point.y}
              r={Math.max(4, metrics.naturalWidth * 0.003)}
              fill="#8aaacb" opacity="0.65"
            />
          ))}

          {marker && (
            <g>
              <circle
                cx={marker.x} cy={marker.y}
                r={Math.max(10, metrics.naturalWidth * 0.007)}
                fill="rgba(230,99,59,0.22)"
              />
              <circle
                cx={marker.x} cy={marker.y}
                r={Math.max(6, metrics.naturalWidth * 0.004)}
                fill="#e6633b" stroke="white" strokeWidth={Math.max(1.5, metrics.naturalWidth * 0.0012)}
              />
            </g>
          )}
        </svg>
      )}
    </div>
  );
};

// ── AdminRoomsScreen ──────────────────────────────────────────────────────────
const AdminRoomsScreen = () => {
  const { lang } = useLang();
  const navigate          = useNavigate();
  const location          = useLocation();
  const {
    buildings,
    buildingsLoading,
    rooms,
    roomsLoading,
    addRoom,
    updateRoom,
    deleteRoom,
  } = useAdmin();

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  const [selectedBldId, setSelectedBldId] = useState(null);
  const [view,          setView]          = useState('list');
  const [form,          setForm]          = useState({ ...EMPTY_ROOM });
  const [confirmId,     setConfirmId]     = useState(null);
  const [error,         setError]         = useState('');

  // Map-based placement mode.
  const [placementMode, setPlacementMode] = useState('map');
  const [buildingMaps, setBuildingMaps] = useState([]);
  const [buildingMapsLoading, setBuildingMapsLoading] = useState(false);
  // Distinct from "genuinely zero maps" (Part 6) — a fetch that actually
  // failed (network/auth) must show "Maps could not be loaded" + Retry,
  // never be silently indistinguishable from an empty-but-successful list.
  const [buildingMapsError, setBuildingMapsError] = useState('');
  const [mapsRetryToken, setMapsRetryToken] = useState(0);
  const [pickerMap, setPickerMap] = useState(null);
  const [pickerRoutePoints, setPickerRoutePoints] = useState([]);
  const [pickerRouteEdges, setPickerRouteEdges] = useState([]);

  // Part 3 — Building -> Map Group -> Floor Map. The Building is this
  // screen's fixed context (selectedBldId), so only these two extra
  // levels are picked here.
  const [selectedMapGroupKey, setSelectedMapGroupKey] = useState(null);

  // Part 4 — one-shot flags so draft restore / newMapId auto-select each
  // only ever run once, not on every re-render.
  const draftRestoredRef = useRef(false);
  const newMapAutoSelectedRef = useRef(false);

  // OCR suggestion state — never applied to the name field automatically;
  // only via the explicit "Use this name" action (applySuggestedName).
  const [ocrLoading, setOcrLoading] = useState(false);
  const [ocrResult, setOcrResult] = useState(null);
  const [ocrError, setOcrError] = useState('');
  const [nameFromOcr, setNameFromOcr] = useState(false);

  const [isSaving, setIsSaving] = useState(false);

  // Buildings load asynchronously, so pick a default selection once they arrive.
  useEffect(() => {
    if (!selectedBldId && buildings.length > 0) {
      setSelectedBldId(buildings[0].id);
    }
  }, [buildings, selectedBldId]);

  // Part 4 — restore a Room draft saved (via saveRoomDraft) right before
  // navigating to Map Management's "Add / Upload New Map" flow. Runs
  // exactly once, on mount — a draft is one-shot by design
  // (loadAndClearRoomDraft already removes it from storage), so this must
  // never re-fire on a later re-render or it would try to restore an
  // already-cleared draft.
  useEffect(() => {
    if (draftRestoredRef.current) return;
    draftRestoredRef.current = true;

    const draft = loadAndClearRoomDraft();
    if (!draft) return;

    setSelectedBldId(draft.buildingId);
    setView(draft.view === 'edit' ? 'edit' : 'add');
    setPlacementMode(draft.placementMode === 'manual' ? 'manual' : 'map');
    setForm({ ...EMPTY_ROOM, ...draft.form });
  }, []);

  const currentRooms = selectedBldId ? (rooms[selectedBldId] || []) : [];
  const currentBld   = buildings.find((b) => b.id === selectedBldId);

  const setField = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  // Load this building's maps whenever the add/edit form (in map mode)
  // needs them — fetched directly via mapsApi.js (not AdminContext's
  // `maps`, which doesn't carry a usable building_id/absolute image URL)
  // so the picker always has real, renderable map data.
  useEffect(() => {
    if (view === 'list' || placementMode !== 'map' || !selectedBldId) return undefined;

    let cancelled = false;
    setBuildingMapsLoading(true);
    setBuildingMapsError('');

    getMaps()
      .then((allMaps) => {
        if (cancelled) return;
        // Sorted ascending by floor (PHASE "Final Submission" Problem 2,
        // requirement: "sort floor maps numerically") so the dropdown
        // always lists Floor -1, Floor 0, Floor 1, Floor 2… in the order
        // an admin expects, never fetch order.
        setBuildingMaps(
          sortFloorsByNumber(
            (Array.isArray(allMaps) ? allMaps : []).filter(
              (m) => m.buildingId === selectedBldId
            )
          )
        );
      })
      .catch((err) => {
        console.error('Failed to load maps for building:', err);
        if (cancelled) return;
        setBuildingMaps([]);
        // Part 6 — a genuine load failure (network/auth) must be visibly
        // distinct from "this building simply has zero maps". If the
        // token expired, apiRequest's shared 401 handling has already
        // cleared the stored session (see api/api.js) — surfacing the
        // real error message here (rather than a generic one) lets the
        // admin see exactly what happened instead of an indefinite
        // "Loading map..." with no explanation.
        setBuildingMapsError(err?.message || t.mapsLoadError);
      })
      .finally(() => {
        if (!cancelled) setBuildingMapsLoading(false);
      });

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, placementMode, selectedBldId, mapsRetryToken]);

  // Part 3 — auto-select the Map Group step when there's only one (or
  // when the previously-selected group no longer exists in the freshly
  // loaded list, e.g. after switching buildings).
  useEffect(() => {
    if (view === 'list' || placementMode !== 'map') return;

    const groupOptions = buildRoomMapGroupOptions(buildingMaps);
    const stillValid = groupOptions.some((option) => option.key === selectedMapGroupKey);

    if (stillValid) return;

    setSelectedMapGroupKey(resolveAutoSelectedMapGroupKey(buildingMaps));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildingMaps, view, placementMode]);

  // Part 3 — auto-select the Floor Map step when there's only one for the
  // currently selected group, but only while the form has no map chosen
  // yet (never override an already-picked/restored-draft/legacy map).
  useEffect(() => {
    if (view === 'list' || placementMode !== 'map' || form.mapId) return;

    const autoFloorMapId = resolveAutoSelectedFloorMapId(buildingMaps, selectedMapGroupKey);
    if (autoFloorMapId) handleSelectMap(autoFloorMapId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildingMaps, selectedMapGroupKey, view, placementMode, form.mapId]);

  // Part 4 — after returning from Map Management with ?newMapId=<id>,
  // auto-select that map as soon as it actually appears in the freshly
  // reloaded buildingMaps list (it may take a beat for processing/
  // normalization, but getMaps() above already reloads on every mount).
  useEffect(() => {
    if (newMapAutoSelectedRef.current) return;

    const newMapId = new URLSearchParams(location.search).get('newMapId');
    if (!newMapId) {
      newMapAutoSelectedRef.current = true;
      return;
    }

    const match = buildingMaps.find((m) => m.id === newMapId);
    if (!match) return;

    setSelectedMapGroupKey(match.mapGroupId || UNGROUPED_MAP_GROUP_KEY);
    handleSelectMap(match.id);
    newMapAutoSelectedRef.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildingMaps, location.search]);

  // Load the selected map's existing corridor graph for context, and
  // resolve the actual Map object for the picker.
  useEffect(() => {
    if (!form.mapId) {
      setPickerMap(null);
      setPickerRoutePoints([]);
      setPickerRouteEdges([]);
      return undefined;
    }

    let cancelled = false;
    const map = buildingMaps.find((m) => m.id === form.mapId) || null;
    setPickerMap(map);

    Promise.all([
      getRoutePoints({ map_id: form.mapId }),
      getRouteEdges({ map_id: form.mapId }),
    ])
      .then(([points, edges]) => {
        if (cancelled) return;
        setPickerRoutePoints(Array.isArray(points) ? points : []);
        setPickerRouteEdges(Array.isArray(edges) ? edges : []);
      })
      .catch((err) => {
        console.error('Failed to load map graph for picker:', err);
        if (!cancelled) {
          setPickerRoutePoints([]);
          setPickerRouteEdges([]);
        }
      });

    return () => { cancelled = true; };
  }, [form.mapId, buildingMaps]);

  // PHASE "Final Submission" Problem 2 — surfaces the exact reproduced bug
  // ("editing only shows an older map") as an explicit, honest warning
  // instead of a silently-stuck blank picker. Only meaningful once
  // buildingMaps has actually finished loading — a still-loading list
  // must never be misread as "this map doesn't exist".
  const mapReferenceStatus = useMemo(() => {
    if (view === 'list' || placementMode !== 'map' || buildingMapsLoading) {
      return { status: 'none' };
    }
    return resolveMapReferenceStatus(form.mapId, buildingMaps);
  }, [view, placementMode, buildingMapsLoading, form.mapId, buildingMaps]);

  // Part 3 — the two picker steps, recomputed straight from buildingMaps
  // so they can never drift from what's actually loaded (no separate
  // "options" state to keep in sync).
  const mapGroupOptions = useMemo(
    () => buildRoomMapGroupOptions(buildingMaps),
    [buildingMaps]
  );
  const floorMapOptions = useMemo(
    () => floorMapsForGroup(buildingMaps, selectedMapGroupKey),
    [buildingMaps, selectedMapGroupKey]
  );

  // Part 7 — never invent a successful graph status; only ever report
  // what the backend actually returned (form.routePointConnected) or an
  // honestly-derived "nothing to connect to" / "map no longer valid"
  // state from data already on screen.
  const describeConnectionStatus = () => {
    if (mapReferenceStatus.status === 'none' || mapReferenceStatus.status === 'legacy') {
      return t.graphInvalidMap;
    }
    if (form.routePointConnected) return t.connected;
    if (pickerRoutePoints.length === 0 && pickerRouteEdges.length === 0) {
      return t.graphNoWalkableGraph;
    }
    return t.graphReviewRequired;
  };

  const openAdd = () => {
    setForm({ ...EMPTY_ROOM });
    setError('');
    setPlacementMode('map');
    setOcrResult(null);
    setOcrError('');
    setNameFromOcr(false);
    setSelectedMapGroupKey(null);
    setBuildingMapsError('');
    setView('add');
  };

  // Section 17 — "Create Destination" on a published semantic entity
  // (see AdminMapAnalysisScreen.jsx's handleCreateDestination) lands here
  // via ?prefillName=&prefillNameAr=&prefillNameHe=&prefillMapId=&
  // prefillSemanticPublicationId=&prefillSemanticEntityExternalId=&
  // prefillSemanticEntityType=. This ONLY prefills the Add Room form's
  // fields (name in all three languages, which building's map, and the
  // semantic-entity link) — it never auto-creates a Room, never invents
  // coordinates/translations the admin didn't already approve, and the
  // admin still goes through the exact same map placement / RoutePoint
  // connection steps as any other new Room. Section 6: the semantic link
  // is copied through here so the created Room keeps a real traceability
  // relation back to the semantic entity it came from.
  const prefillConsumedRef = useRef(false);
  useEffect(() => {
    if (prefillConsumedRef.current) return;
    const params = new URLSearchParams(location.search);
    const prefillName = params.get('prefillName');
    const prefillNameAr = params.get('prefillNameAr');
    const prefillNameHe = params.get('prefillNameHe');
    const prefillMapId = params.get('prefillMapId');
    const prefillSemanticPublicationId = params.get('prefillSemanticPublicationId');
    const prefillSemanticEntityExternalId = params.get('prefillSemanticEntityExternalId');
    const prefillSemanticEntityType = params.get('prefillSemanticEntityType');
    if (
      !prefillName && !prefillNameAr && !prefillNameHe && !prefillMapId
      && !prefillSemanticEntityExternalId
    ) return;

    prefillConsumedRef.current = true;
    openAdd();
    setForm((prev) => ({
      ...prev,
      name: prefillName || prev.name,
      nameAr: prefillNameAr || prev.nameAr,
      nameHe: prefillNameHe || prev.nameHe,
      mapId: prefillMapId || prev.mapId,
      semanticPublicationId: prefillSemanticPublicationId || prev.semanticPublicationId,
      semanticEntityExternalId: prefillSemanticEntityExternalId || prev.semanticEntityExternalId,
      semanticEntityType: prefillSemanticEntityType || prev.semanticEntityType,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search]);

  const openEdit = (r) => {
    setForm({ ...EMPTY_ROOM, ...r });
    setError('');
    setPlacementMode(r.mapId && r.x !== null && r.y !== null ? 'map' : 'manual');
    setOcrResult(null);
    setOcrError('');
    setNameFromOcr(false);
    // Pre-select the Room's own Map Group when known, instead of letting
    // the auto-select effect briefly pick a different (e.g. first-listed)
    // group before snapping back — avoids a visible flicker on open.
    setSelectedMapGroupKey(r.mapGroupId || null);
    setBuildingMapsError('');
    setView('edit');
  };

  // Part 4 — preserve the in-progress draft, then hand off to Admin Map
  // Management's existing upload workflow. Never creates a Map itself.
  const handleAddNewMap = () => {
    saveRoomDraft({ buildingId: selectedBldId, view, placementMode, form });
    const params = new URLSearchParams({
      openUpload: '1',
      buildingId: selectedBldId || '',
      returnTo: '/admin/rooms',
    });
    navigate(`/admin/map?${params.toString()}`);
  };

  // Part 6 — explicit retry, distinct from the silent auto-refetch that
  // already happens whenever selectedBldId/view/placementMode change.
  const handleRetryMaps = () => setMapsRetryToken((prev) => prev + 1);

  const handlePickLocation = (x, y) => {
    setField('x', x);
    setField('y', y);
    setOcrResult(null);
    setOcrError('');
  };

  const handleClearMarker = () => {
    setField('x', null);
    setField('y', null);
    setOcrResult(null);
    setOcrError('');
  };

  const handleSelectMap = (mapId) => {
    setField('mapId', mapId || null);
    setField('x', null);
    setField('y', null);
    setOcrResult(null);
    setOcrError('');

    const map = buildingMaps.find((m) => m.id === mapId);
    if (map && (map.floor ?? null) !== null) {
      setField('floor', map.floor);
    }
  };

  const handleSuggestName = async () => {
    if (!form.mapId || form.x === null || form.y === null) return;

    setOcrLoading(true);
    setOcrError('');

    try {
      const result = await suggestDestinationName(form.mapId, { x: form.x, y: form.y });
      setOcrResult(result);
    } catch (err) {
      console.error('OCR suggestion failed:', err);
      setOcrError(err.message || 'OCR suggestion failed');
      setOcrResult(null);
    } finally {
      setOcrLoading(false);
    }
  };

  const handleUseOcrName = () => {
    if (!ocrSummary?.canApply) return;
    setField('name', applySuggestedName(ocrSummary.text));
    setNameFromOcr(true);
  };

  const ocrSummary = ocrResult ? summarizeOcrSuggestion(ocrResult) : null;

  const handleSave = async () => {
    if (!selectedBldId) return;

    if (placementMode === 'map' && (form.x === null || form.y === null || !form.mapId)) {
      setError(t.savePlacementError);
      return;
    }

    // Never silently re-save a legacy map reference — Part 12's explicit
    // rule. The admin must pick a current floor map (which also clears
    // x/y via handleSelectMap) before Save is allowed to proceed.
    if (placementMode === 'map' && mapReferenceStatus.status === 'legacy') {
      setError(t.legacyMapWarning);
      return;
    }

    const entry = { ...form, floor: Number(form.floor) };
    if (placementMode === 'manual') {
      entry.mapId = null;
      entry.x = null;
      entry.y = null;
    }

    setIsSaving(true);
    setError('');

    try {
      const saved = view === 'add'
        ? await addRoom(selectedBldId, entry)
        : await updateRoom(selectedBldId, entry);

      if (placementMode === 'map' && saved) {
        const summaryLines = [
          t.saveSummaryTitle,
          t.saveSummaryPoint(saved.routePointWasReused),
          t.saveSummaryConnection(saved.routePointConnected),
          t.saveSummaryOcr(nameFromOcr),
        ];
        alert(summaryLines.join('\n'));
      }

      setView('list');
    } catch (err) {
      console.error('Failed to save room:', err);
      setError(err.message || t.saveError);
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (id) => {
    if (!selectedBldId) return;

    try {
      await deleteRoom(selectedBldId, id);
      setConfirmId(null);
    } catch (err) {
      console.error('Failed to delete room:', err);
      setError(err.message || t.deleteError);
      setConfirmId(null);
    }
  };

  return (
    <div className="qrd-page">
      <div className="qrd-pagebody" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="qrd-headwrap">
          <AdminScreenHeader
            pageKey="rooms"
            onBack={view !== 'list' ? () => setView('list') : undefined}
          />
        </div>

        {/* ── Content ─────────────────────────────────────────────────── */}
        <div className="adm-content">

          {error && (
            <div style={{
              marginBottom: 16, padding: 12, borderRadius: 12,
              background: '#ffe9e9', color: '#a92323', fontSize: 14,
            }}>
              {error}
            </div>
          )}

          {/* ── List view ── */}
          {view === 'list' && buildingsLoading && (
            <div className="adm-empty">
              <div className="adm-empty-txt">{t.loading}</div>
            </div>
          )}

          {view === 'list' && !buildingsLoading && buildings.length === 0 && (
            <div className="adm-empty">
              <div className="adm-empty-icon"><RoomIcon /></div>
              <div className="adm-empty-txt">{t.noBuildings}</div>
              <div className="adm-empty-hint">{t.noBuildingsHint}</div>
            </div>
          )}

          {view === 'list' && !buildingsLoading && buildings.length > 0 && (
            <>
              {/* Building selector tabs */}
              <div className="adm-building-tabs">
                {buildings.map((b) => (
                  <button
                    key={b.id}
                    className={`adm-building-tab${selectedBldId === b.id ? ' active' : ''}`}
                    style={selectedBldId === b.id
                      ? { background: `linear-gradient(135deg, ${b.iconColor}cc, ${b.iconColor})` }
                      : {}}
                    onClick={() => { setSelectedBldId(b.id); setConfirmId(null); }}
                  >
                    {b.tag}
                  </button>
                ))}
              </div>

              {/* Building label */}
              {currentBld && (
                <div className="adm-section-row">
                  <span className="adm-section-lbl">{currentBld.nameEn}</span>
                  <span className="adm-section-count">{t.count(currentRooms.length)}</span>
                </div>
              )}

              <div className="adm-btn-row">
                <button className="adm-btn adm-btn-primary" onClick={openAdd}
                  disabled={!selectedBldId}>
                  <AddIcon /> {t.addBtn}
                </button>
              </div>

              {roomsLoading ? (
                <div className="adm-empty">
                  <div className="adm-empty-txt">{t.loading}</div>
                </div>
              ) : currentRooms.length === 0 ? (
                <div className="adm-empty">
                  <div className="adm-empty-icon"><RoomIcon /></div>
                  <div className="adm-empty-txt">{t.empty}</div>
                  <div className="adm-empty-hint">{t.emptyHint}</div>
                </div>
              ) : (
                <div className="adm-list">
                  {currentRooms.map((r) => (
                    <div key={r.id} className="adm-list-item">
                      <div className="adm-list-item-row">
                        <div className="adm-list-item-info">
                          {/* DISPLAY ONLY. `r.name` is this admin
                              screen's EDITABLE English value — it is what
                              openEdit() loads into the "Room Name (EN)"
                              input and what AdminContext's
                              roomToApiPayload sends as name_en/names.en.
                              So it is deliberately left untouched here and
                              only the rendered string is resolved for the
                              current UI language, through the same shared
                              helper (and the same fallback chain) that
                              DestinationSelectionScreen already uses. A
                              room with no ar/he value keeps showing
                              exactly the English name it shows today. */}
                          <div className="adm-list-item-name">
                            {getLocalizedText(r.names, lang, r.name)}
                          </div>
                          <div className="adm-list-item-meta">
                            <span className={`adm-tag ${GROUP_COLOR[typeToGroupKey(r.type)] || 'adm-tag-blue'}`}>
                              {resolveDestinationTypeLabel(r.type, t.typeLabels)}
                            </span>
                            <span className="adm-tag-txt">{formatFloorDisplay(r.floor, null)}</span>
                            {r.routePointId && (
                              // Live status (isNavigable), never the
                              // create/update-only one-shot
                              // routePointConnected signal — this list is
                              // populated via a plain GET, which always
                              // returns routePointConnected=false.
                              <span className={`adm-tag ${r.isNavigable ? 'adm-tag-green' : 'adm-tag-orange'}`}>
                                {r.isNavigable ? t.connected : t.notConnected.split('—')[0].trim()}
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="adm-list-item-acts">
                          <button className="adm-icon-btn" onClick={() => openEdit(r)}>
                            <EditIcon />
                          </button>
                          <button className="adm-icon-btn adm-icon-btn-danger"
                            onClick={() => setConfirmId(confirmId === r.id ? null : r.id)}>
                            <DeleteIcon />
                          </button>
                        </div>
                      </div>

                      {confirmId === r.id && (
                        <div className="adm-delete-strip">
                          <span className="adm-delete-strip-msg">{t.confirmDelete}</span>
                          <div className="adm-delete-strip-acts">
                            <button className="adm-btn adm-btn-cancel"
                              style={{ padding: '5px 12px', fontSize: 12 }}
                              onClick={() => setConfirmId(null)}>
                              {t.cancel}
                            </button>
                            <button className="adm-btn adm-btn-confirm-delete"
                              style={{ padding: '5px 12px', fontSize: 12 }}
                              onClick={() => handleDelete(r.id)}>
                              {t.yes}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {/* ── Add / Edit form ── */}
          {(view === 'add' || view === 'edit') && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">
                {view === 'add' ? t.addTitle : t.editTitle}
                {currentBld && (
                  <span style={{ fontSize: 12, color: '#8aaacb', fontWeight: 600,
                    marginLeft: 8, marginRight: 8 }}>
                    — {currentBld.nameEn}
                  </span>
                )}
              </div>

              {/* Placement mode toggle — map-based is the primary flow,
                  manual entry is kept as an explicit fallback. */}
              <div className="adm-building-tabs" style={{ marginBottom: 14 }}>
                <button
                  className={`adm-building-tab${placementMode === 'map' ? ' active' : ''}`}
                  style={placementMode === 'map' ? { background: 'linear-gradient(135deg, #1a3a6bcc, #2a5298)' } : {}}
                  onClick={() => setPlacementMode('map')}
                >
                  {t.modeMap}
                </button>
                <button
                  className={`adm-building-tab${placementMode === 'manual' ? ' active' : ''}`}
                  style={placementMode === 'manual' ? { background: 'linear-gradient(135deg, #1a3a6bcc, #2a5298)' } : {}}
                  onClick={() => setPlacementMode('manual')}
                >
                  {t.modeManual}
                </button>
              </div>

              {placementMode === 'map' && (
                <>
                  {/* Part 6 — loading state: never leave a blank/disabled
                      dropdown with no explanation while maps are in flight. */}
                  {buildingMapsLoading && (
                    <div className="adm-form-group">
                      <div className="adm-form-hint">{t.loadingMaps}</div>
                    </div>
                  )}

                  {/* Part 6 — genuine load failure (network/auth), distinct
                      from "this building simply has zero maps". Never a
                      dummy/fallback Map — Retry re-fetches for real. */}
                  {!buildingMapsLoading && buildingMapsError && (
                    <div className="adm-form-group">
                      <div className="adm-setup-card-error">{t.mapsLoadError}</div>
                      <div className="adm-btn-row" style={{ marginTop: 8 }}>
                        <button type="button" className="adm-btn adm-btn-secondary" onClick={handleRetryMaps}>
                          {t.retryMaps}
                        </button>
                        <button type="button" className="adm-btn adm-btn-secondary" onClick={handleAddNewMap}>
                          {t.addUploadMap}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Part 6 — genuinely zero maps for this building. */}
                  {!buildingMapsLoading && !buildingMapsError && buildingMaps.length === 0 && (
                    <div className="adm-form-group">
                      <div className="adm-form-hint">{t.noMapsConfigured}</div>
                      <div className="adm-btn-row" style={{ marginTop: 8 }}>
                        <button type="button" className="adm-btn adm-btn-secondary" onClick={handleAddNewMap}>
                          {t.addUploadMap}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Part 3 — Map Group -> Floor Map two-step picker. The
                      Map Group step is only shown when there's an actual
                      choice to make (single-group buildings skip straight
                      to Floor Map, already auto-selected). */}
                  {!buildingMapsLoading && !buildingMapsError && buildingMaps.length > 0 && (
                    <>
                      {mapGroupOptions.length > 1 && (
                        <div className="adm-form-group">
                          <label className="adm-form-label">{t.selectMapGroup}</label>
                          <select
                            className="adm-form-select"
                            value={selectedMapGroupKey || ''}
                            onChange={(e) => {
                              setSelectedMapGroupKey(e.target.value || null);
                              handleSelectMap(null);
                            }}
                          >
                            <option value="">{t.selectMapGroupPlaceholder}</option>
                            {mapGroupOptions.map((g) => (
                              <option key={g.key} value={g.key}>
                                {g.code || t.selectFloorMap}
                              </option>
                            ))}
                          </select>
                        </div>
                      )}

                      {(mapGroupOptions.length <= 1 || selectedMapGroupKey) && (
                        <div className="adm-form-group">
                          <label className="adm-form-label">{t.selectFloorMap}</label>
                          <select
                            className="adm-form-select"
                            value={form.mapId || ''}
                            onChange={(e) => handleSelectMap(e.target.value)}
                          >
                            <option value="">{t.selectFloorMapPlaceholder}</option>
                            {floorMapOptions.map((m) => (
                              <option key={m.id} value={m.id}>
                                {buildFloorMapOptionLabel(m)}
                              </option>
                            ))}
                          </select>
                        </div>
                      )}

                      <div className="adm-btn-row" style={{ marginTop: 4, marginBottom: 8 }}>
                        <button type="button" className="adm-btn adm-btn-secondary" onClick={handleAddNewMap}>
                          {t.addUploadMap}
                        </button>
                      </div>
                    </>
                  )}

                  {mapReferenceStatus.status === 'legacy' && (
                    <div className="adm-setup-card-error" style={{ marginBottom: 12 }}>
                      <div>{t.legacyMapWarning}</div>
                      <div style={{ marginTop: 4, fontWeight: 400 }}>{t.legacyMapReassign}</div>
                    </div>
                  )}

                  {form.mapId && mapReferenceStatus.status !== 'legacy' && (
                    <>
                      <div className="adm-form-hint" style={{ marginBottom: 8 }}>
                        {t.clickMapHint}
                      </div>

                      <MapDestinationPicker
                        map={pickerMap}
                        routePoints={pickerRoutePoints}
                        routeEdges={pickerRouteEdges}
                        marker={form.x !== null && form.y !== null ? { x: form.x, y: form.y } : null}
                        onPick={handlePickLocation}
                        t={t}
                      />

                      <div className="adm-btn-row" style={{ marginTop: 10 }}>
                        <span className="adm-tag-txt">
                          {form.x !== null && form.y !== null ? t.markerSet : t.markerNotSet}
                        </span>
                        {form.x !== null && form.y !== null && (
                          <button className="adm-btn adm-btn-secondary" onClick={handleClearMarker}>
                            {t.clearMarker}
                          </button>
                        )}
                      </div>

                      {form.x !== null && form.y !== null && (
                        <div className="adm-btn-row">
                          <button
                            className="adm-btn adm-btn-secondary"
                            onClick={handleSuggestName}
                            disabled={ocrLoading}
                          >
                            {ocrLoading ? t.suggestingName : t.suggestName}
                          </button>
                        </div>
                      )}

                      {ocrError && (
                        <div className="adm-setup-card-error">{ocrError}</div>
                      )}

                      {ocrSummary && (
                        <div className="adm-ocr-box">
                          {ocrSummary.canApply ? (
                            <>
                              <div className="adm-ocr-box-text">"{ocrSummary.text}"</div>
                              {ocrSummary.lowConfidence && (
                                <div className="adm-ocr-box-warn">{t.ocrLowConfidence}</div>
                              )}
                              <button
                                className="adm-btn adm-btn-secondary"
                                style={{ marginTop: 8 }}
                                onClick={handleUseOcrName}
                              >
                                {t.useThisName}
                              </button>
                            </>
                          ) : (
                            <>
                              <div className="adm-ocr-box-warn">{ocrSummary.message}</div>
                              <div className="adm-form-hint">{t.ocrUnavailableHint}</div>
                            </>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </>
              )}

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.name}</label>
                <input className="adm-form-input" value={form.name || ''}
                  onChange={(e) => { setField('name', e.target.value); setNameFromOcr(false); }}
                  placeholder="e.g. Cardiac Emergency Unit" />
              </div>
              {/* Independently-editable AR/HE translations (Section 4/5 of
                  the multilingual spec) — never auto-copied from/into the
                  EN field above or each other; an admin leaving one blank
                  simply means that language falls back to EN for a real
                  user (see utils/localization.js's getLocalizedText). */}
              <div className="adm-form-row">
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.nameAr}</label>
                  <input className="adm-form-input" value={form.nameAr || ''}
                    onChange={(e) => setField('nameAr', e.target.value)}
                    placeholder={t.emptyTranslation} dir="rtl" />
                </div>
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.nameHe}</label>
                  <input className="adm-form-input" value={form.nameHe || ''}
                    onChange={(e) => setField('nameHe', e.target.value)}
                    placeholder={t.emptyTranslation} dir="rtl" />
                </div>
              </div>
              <div className="adm-form-row">
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.type}</label>
                  <select className="adm-form-select" value={form.type || 'room'}
                    onChange={(e) => setField('type', e.target.value)}>
                    {buildDestinationTypeSelectGroups(form.type, t.typeLabels, t.typeGroupLabels).map((group) => (
                      <optgroup key={group.groupKey} label={group.groupLabel}>
                        {group.options.map((opt) => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </div>
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.floor}</label>
                  <input className="adm-form-input" type="number" value={form.floor ?? 0}
                    onChange={(e) => setField('floor', e.target.value)}
                    placeholder="0" />
                </div>
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.description}</label>
                <textarea className="adm-form-textarea" value={form.description || ''}
                  onChange={(e) => setField('description', e.target.value)}
                  placeholder="Brief description…" />
              </div>

              {placementMode === 'map' && form.routePointId && (
                <div className="adm-form-group">
                  <span className={`adm-tag ${form.routePointConnected ? 'adm-tag-green' : 'adm-tag-orange'}`}>
                    {t.connectionStatus}: {describeConnectionStatus()}
                  </span>
                </div>
              )}

              <div className="adm-form-actions">
                <button className="adm-btn adm-btn-cancel" onClick={() => setView('list')}>
                  {t.cancel}
                </button>
                <button className="adm-btn adm-btn-primary" onClick={handleSave} disabled={isSaving}>
                  {t.save}
                </button>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
};

export default AdminRoomsScreen;
