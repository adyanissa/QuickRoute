import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import {
  getMaps,
  updateMap as apiUpdateMap,
  deleteMap as apiDeleteMap,
  uploadMap as apiUploadMap,
  getMapProcessingStatus,
  normalizeMap,
} from '../api/mapsApi';
import {
  getRoutePoints,
  createRoutePoint,
  deleteRoutePoint,
} from '../api/routePointsApi';
import {
  getRouteEdges,
  createRouteEdge,
  deleteRouteEdge,
} from '../api/routeEdgesApi';
import { getBuildings } from '../api/buildingsApi';
import { getRooms } from '../api/roomsApi';
import { calculateRoute } from '../api/navigationApi';
import { findNearestPointWithinThreshold } from '../utils/geometry';
import '../styles/adminScreens.css';

// Snap threshold for Draw Walkable Path, in original-image pixels.
const SNAP_THRESHOLD_PX = 18;

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const UI = {
  en: {
    title: 'Map Management',
    back: 'Back',
    selectMap: 'Select Map',
    uploadNewMap: 'Upload New Map',
    editDetails: 'Edit Details',
    deleteMap: 'Delete Map',
    selectedMap: 'Selected Map',
    current: 'Current',
    noMap: 'No map uploaded yet',
    noMapHint: 'Upload a map image or PDF to get started',
    openFullMap: 'Click map to open full view',
    savedPoints: 'Saved points',
    noPoints: 'No route points saved for this map yet',
    savedEdges: 'Saved edges',
    noEdges: 'No route edges saved for this map yet',
    loadingMaps: 'Loading maps...',
    loadingPoints: 'Loading route points...',
    loadingEdges: 'Loading route edges...',
    mapsError: 'Failed to load maps',
    pointsError: 'Failed to load route points',
    edgesError: 'Failed to load route edges',
    edgeDataWarning:
      'route edge(s) reference a route point that is missing from this map and were not drawn',
    addPointMode: 'Add Point',
    drawMode: 'Draw Walkable Path',
    drawHint: 'Click the map to add corridor points. Click near an existing point to reuse it.',
    drawFloor: 'Floor',
    drawUndo: 'Undo',
    drawClear: 'Clear',
    drawCancel: 'Cancel',
    drawSave: 'Save Path',
    drawSaving: 'Saving...',
    drawNeedTwo: 'Add at least 2 points before saving',
    drawSaveSuccess: (points, edges) =>
      `Saved ${points} point${points === 1 ? '' : 's'} and ${edges} edge${edges === 1 ? '' : 's'}`,
    drawSaveFailed: 'Could not save the path. Any newly created points and edges were rolled back.',
    drawPointCount: (n) => `${n} point${n === 1 ? '' : 's'} in draft`,
    drawReusedPoint: 'existing point reused',
    building: 'Building',
    room: 'Room',
    selectBuilding: 'Select a building',
    selectRoom: 'Select a room',
    connectNearest: 'Connect to nearest corridor point',
    roomAlreadyLinked: (name) => `This room is already linked to "${name}"`,
    testMode: 'Test Route',
    testStart: 'Start point',
    testEnd: 'Destination point',
    testSelectStart: 'Select a start point',
    testSelectEnd: 'Select a destination',
    testFind: 'Find Route',
    testClear: 'Clear Test',
    testChangeStart: 'Change Start',
    testChangeEnd: 'Change Destination',
    testCalculating: 'Calculating route...',
    testNoRoute: 'No route found between these points',
    testDistance: (meters) => `Total distance: ${meters.toFixed(1)} m`,
    testStepCount: (n) => `${n} point${n === 1 ? '' : 's'} on this route`,
    processing: 'Processing map',
    processingFailed: 'Map processing failed',
    confirmDelete: 'Delete the selected map?',
    yesDelete: 'Yes, Delete',
    cancel: 'Cancel',
    addPoint: 'Add Route Point',
    savePoint: 'Save Route Point',
    savedPoint: 'Route point saved',
    selectPoint: 'Click on the map to select a route point',
    pointName: 'Point Name',
    pointType: 'Point Type',
    floor: 'Floor',
    noSelectedMap: 'No map selected',
    uploadTitle: 'Upload a New Map',
    chooseFile: 'Choose map file',
    selectedFile: 'Selected file',
    mapTitle: 'Map Title',
    campus: 'Campus / Location',
    address: 'Address',
    description: 'Description',
    scale: 'Map Scale',
    useOpenAI: 'Use OpenAI processing',
    upload: 'Upload Map',
    uploading: 'Uploading...',
    uploadSuccess:
      'Map uploaded successfully. Processing started automatically.',
    uploadError: 'Failed to upload map',
    requiredUploadFields: 'Map title and file are required',
    editTitle: 'Edit Map Details',
    saveChanges: 'Save Changes',
    details: {
      title: 'Title',
      campus: 'Campus',
      address: 'Address',
      description: 'Description',
      status: 'Status',
      mapId: 'Map ID',
    },
  },

  ar: {
    title: 'إدارة الخريطة',
    back: 'رجوع',
    selectMap: 'اختيار الخريطة',
    uploadNewMap: 'رفع خارطة جديدة',
    editDetails: 'تعديل التفاصيل',
    deleteMap: 'حذف الخريطة',
    selectedMap: 'الخريطة المختارة',
    current: 'الحالية',
    noMap: 'لا توجد خريطة مرفوعة',
    noMapHint: 'ارفعي صورة خارطة أو ملف PDF للبدء',
    openFullMap: 'اضغطي على الخريطة لفتحها كاملة',
    savedPoints: 'النقاط المحفوظة',
    noPoints: 'لا توجد نقاط محفوظة لهذه الخريطة بعد',
    savedEdges: 'الحواف المحفوظة',
    noEdges: 'لا توجد حواف مسار محفوظة لهذه الخريطة بعد',
    loadingMaps: 'جاري تحميل الخرائط...',
    loadingPoints: 'جاري تحميل نقاط المسار...',
    loadingEdges: 'جاري تحميل حواف المسار...',
    mapsError: 'فشل تحميل الخرائط',
    pointsError: 'فشل تحميل نقاط المسار',
    edgesError: 'فشل تحميل حواف المسار',
    edgeDataWarning: 'حافة/حواف مسار تشير إلى نقطة غير موجودة في هذه الخريطة ولم تُرسم',
    addPointMode: 'إضافة نقطة',
    drawMode: 'رسم مسار للمشي',
    drawHint: 'اضغطي على الخريطة لإضافة نقاط الممر. اضغطي بالقرب من نقطة موجودة لإعادة استخدامها.',
    drawFloor: 'الطابق',
    drawUndo: 'تراجع',
    drawClear: 'مسح',
    drawCancel: 'إلغاء',
    drawSave: 'حفظ المسار',
    drawSaving: 'جاري الحفظ...',
    drawNeedTwo: 'أضيفي نقطتين على الأقل قبل الحفظ',
    drawSaveSuccess: (points, edges) => `تم حفظ ${points} نقطة و ${edges} حافة`,
    drawSaveFailed: 'تعذر حفظ المسار. تم التراجع عن أي نقاط وحواف تم إنشاؤها حديثًا.',
    drawPointCount: (n) => `${n} نقطة في المسودة`,
    drawReusedPoint: 'إعادة استخدام نقطة موجودة',
    building: 'المبنى',
    room: 'الغرفة',
    selectBuilding: 'اختر مبنى',
    selectRoom: 'اختر غرفة',
    connectNearest: 'الاتصال بأقرب نقطة ممر',
    roomAlreadyLinked: (name) => `هذه الغرفة مرتبطة بالفعل بـ "${name}"`,
    testMode: 'اختبار المسار',
    testStart: 'نقطة البداية',
    testEnd: 'نقطة الوجهة',
    testSelectStart: 'اختر نقطة البداية',
    testSelectEnd: 'اختر الوجهة',
    testFind: 'ابحث عن مسار',
    testClear: 'مسح الاختبار',
    testChangeStart: 'تغيير البداية',
    testChangeEnd: 'تغيير الوجهة',
    testCalculating: 'جاري حساب المسار...',
    testNoRoute: 'لم يتم العثور على مسار بين هاتين النقطتين',
    testDistance: (meters) => `المسافة الإجمالية: ${meters.toFixed(1)} م`,
    testStepCount: (n) => `${n} نقطة على هذا المسار`,
    processing: 'جاري تجهيز الخريطة',
    processingFailed: 'فشلت معالجة الخريطة',
    confirmDelete: 'حذف الخريطة المختارة؟',
    yesDelete: 'نعم، احذف',
    cancel: 'إلغاء',
    addPoint: 'إضافة نقطة مسار',
    savePoint: 'حفظ نقطة المسار',
    savedPoint: 'تم حفظ نقطة المسار',
    selectPoint: 'اضغطي على الخريطة لاختيار نقطة مسار',
    pointName: 'اسم النقطة',
    pointType: 'نوع النقطة',
    floor: 'الطابق',
    noSelectedMap: 'لا توجد خريطة مختارة',
    uploadTitle: 'رفع خارطة جديدة',
    chooseFile: 'اختيار ملف الخريطة',
    selectedFile: 'الملف المختار',
    mapTitle: 'اسم الخريطة',
    campus: 'الحرم / الموقع',
    address: 'العنوان',
    description: 'الوصف',
    scale: 'مقياس الخريطة',
    useOpenAI: 'استخدام OpenAI لمعالجة الصورة',
    upload: 'رفع الخريطة',
    uploading: 'جاري الرفع...',
    uploadSuccess: 'تم رفع الخريطة وبدأ تجهيزها تلقائيًا.',
    uploadError: 'فشل رفع الخريطة',
    requiredUploadFields: 'اسم الخريطة والملف مطلوبان',
    editTitle: 'تعديل تفاصيل الخريطة',
    saveChanges: 'حفظ التغييرات',
    details: {
      title: 'الاسم',
      campus: 'الحرم',
      address: 'العنوان',
      description: 'الوصف',
      status: 'الحالة',
      mapId: 'رقم الخريطة',
    },
  },

  he: {
    title: 'ניהול מפה',
    back: 'חזרה',
    selectMap: 'בחירת מפה',
    uploadNewMap: 'העלאת מפה חדשה',
    editDetails: 'ערוך פרטים',
    deleteMap: 'מחק מפה',
    selectedMap: 'מפה נבחרת',
    current: 'נוכחית',
    noMap: 'לא הועלתה מפה',
    noMapHint: 'העלי תמונת מפה או PDF כדי להתחיל',
    openFullMap: 'לחצי על המפה כדי לפתוח תצוגה מלאה',
    savedPoints: 'נקודות שמורות',
    noPoints: 'עדיין אין נקודות שמורות למפה זו',
    savedEdges: 'קשתות שמורות',
    noEdges: 'עדיין אין קשתות מסלול שמורות למפה זו',
    loadingMaps: 'טוען מפות...',
    loadingPoints: 'טוען נקודות מסלול...',
    loadingEdges: 'טוען קשתות מסלול...',
    mapsError: 'טעינת המפות נכשלה',
    pointsError: 'טעינת נקודות המסלול נכשלה',
    edgesError: 'טעינת קשתות המסלול נכשלה',
    edgeDataWarning: 'קשת/קשתות מסלול מצביעות על נקודה שלא נמצאה במפה זו ולא צוירו',
    addPointMode: 'הוסף נקודה',
    drawMode: 'צייר מסלול הליכה',
    drawHint: 'לחצי על המפה כדי להוסיף נקודות מסדרון. לחצי ליד נקודה קיימת כדי לעשות בה שימוש חוזר.',
    drawFloor: 'קומה',
    drawUndo: 'בטל',
    drawClear: 'נקה',
    drawCancel: 'ביטול',
    drawSave: 'שמור מסלול',
    drawSaving: 'שומר...',
    drawNeedTwo: 'הוסף לפחות 2 נקודות לפני השמירה',
    drawSaveSuccess: (points, edges) => `נשמרו ${points} נקודות ו-${edges} קשתות`,
    drawSaveFailed: 'לא ניתן היה לשמור את המסלול. נקודות וקשתות שנוצרו לאחרונה בוטלו.',
    drawPointCount: (n) => `${n} נקודות בטיוטה`,
    drawReusedPoint: 'שימוש חוזר בנקודה קיימת',
    building: 'מבנה',
    room: 'חדר',
    selectBuilding: 'בחר מבנה',
    selectRoom: 'בחר חדר',
    connectNearest: 'חבר לנקודת המסדרון הקרובה ביותר',
    roomAlreadyLinked: (name) => `החדר הזה כבר מקושר ל-"${name}"`,
    testMode: 'בדיקת מסלול',
    testStart: 'נקודת התחלה',
    testEnd: 'נקודת יעד',
    testSelectStart: 'בחר נקודת התחלה',
    testSelectEnd: 'בחר יעד',
    testFind: 'מצא מסלול',
    testClear: 'נקה בדיקה',
    testChangeStart: 'שנה התחלה',
    testChangeEnd: 'שנה יעד',
    testCalculating: 'מחשב מסלול...',
    testNoRoute: 'לא נמצא מסלול בין הנקודות הללו',
    testDistance: (meters) => `מרחק כולל: ${meters.toFixed(1)} מ'`,
    testStepCount: (n) => `${n} נקודות במסלול זה`,
    processing: 'מעבד את המפה',
    processingFailed: 'עיבוד המפה נכשל',
    confirmDelete: 'למחוק את המפה שנבחרה?',
    yesDelete: 'כן, מחק',
    cancel: 'ביטול',
    addPoint: 'הוסף נקודת מסלול',
    savePoint: 'שמור נקודת מסלול',
    savedPoint: 'נקודת המסלול נשמרה',
    selectPoint: 'לחצי על המפה כדי לבחור נקודת מסלול',
    pointName: 'שם הנקודה',
    pointType: 'סוג הנקודה',
    floor: 'קומה',
    noSelectedMap: 'לא נבחרה מפה',
    uploadTitle: 'העלאת מפה חדשה',
    chooseFile: 'בחירת קובץ מפה',
    selectedFile: 'הקובץ שנבחר',
    mapTitle: 'שם המפה',
    campus: 'קמפוס / מיקום',
    address: 'כתובת',
    description: 'תיאור',
    scale: 'קנה מידה',
    useOpenAI: 'השתמש ב-OpenAI לעיבוד התמונה',
    upload: 'העלה מפה',
    uploading: 'מעלה...',
    uploadSuccess: 'המפה הועלתה והעיבוד התחיל אוטומטית.',
    uploadError: 'העלאת המפה נכשלה',
    requiredUploadFields: 'שם המפה והקובץ הם שדות חובה',
    editTitle: 'עריכת פרטי מפה',
    saveChanges: 'שמור שינויים',
    details: {
      title: 'שם',
      campus: 'קמפוס',
      address: 'כתובת',
      description: 'תיאור',
      status: 'סטטוס',
      mapId: 'מזהה מפה',
    },
  },
};

const INITIAL_UPLOAD_FORM = {
  title: '',
  campus: '',
  address: '',
  description: '',
  scale: 1,
  useOpenAI: false,
};

const BackArrow = ({ flip }) => (
  <svg
    width="15"
    height="15"
    viewBox="0 0 24 24"
    fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}
  >
    <path
      d="M19 12H5M11 18l-6-6 6-6"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const MapIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path
      d="M9 20L3 17V4l6 3M9 20l6-3M9 20V7M15 17l6 3V7l-6-3M15 17V4M9 7l6-3"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const UploadIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
    <path
      d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const EditIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <path
      d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />

    <path
      d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const DeleteIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <polyline
      points="3 6 5 6 21 6"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />

    <path
      d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const AdminMapScreen = () => {
  const { lang, setLang } = useLang();
  const navigate = useNavigate();

  const isRTL =
    lang === 'ar' ||
    lang === 'he';

  const t = UI[lang] || UI.en;

  const [view, setView] = useState('detail');

  const [maps, setMaps] = useState([]);
  const [selectedMapId, setSelectedMapId] = useState('');
  const [isMapsLoading, setIsMapsLoading] = useState(false);
  const [mapsError, setMapsError] = useState('');

  const [routePoints, setRoutePoints] = useState([]);
  const [isPointsLoading, setIsPointsLoading] = useState(false);
  const [pointsError, setPointsError] = useState('');

  const [routeEdges, setRouteEdges] = useState([]);
  const [isEdgesLoading, setIsEdgesLoading] = useState(false);
  const [edgesError, setEdgesError] = useState('');

  const [form, setForm] = useState({});

  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [uploadForm, setUploadForm] = useState(
    INITIAL_UPLOAD_FORM,
  );
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadPreview, setUploadPreview] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [pollingMapId, setPollingMapId] = useState('');

  const [isMapOpen, setIsMapOpen] = useState(false);
  const [fullMapMetrics, setFullMapMetrics] = useState(null);
  const [clickedPoint, setClickedPoint] = useState(null);
  const [pointName, setPointName] = useState('');
  const [pointType, setPointType] = useState('hallway');
  const [floor, setFloor] = useState(0);

  // ── Connect Place: link a room/store point to a building + room ───────────
  const [buildingsList, setBuildingsList] = useState([]);
  const [roomsList, setRoomsList] = useState([]);
  const [isRoomsLoading, setIsRoomsLoading] = useState(false);
  const [selectedBuildingId, setSelectedBuildingId] = useState('');
  const [selectedRoomId, setSelectedRoomId] = useState('');
  const [connectToNearest, setConnectToNearest] = useState(true);

  const isPlaceType = pointType === 'room' || pointType === 'store';

  // ── Test Route mode ─────────────────────────────────────────────────────────
  const [testStartId, setTestStartId] = useState('');
  const [testEndId, setTestEndId] = useState('');
  const [testResult, setTestResult] = useState(null);
  const [isTestLoading, setIsTestLoading] = useState(false);
  const [testError, setTestError] = useState('');

  // ── Admin map editing modes ─────────────────────────────────────────────────
  // 'point' is the original click-to-add-a-single-point behavior.
  // 'draw'  is the Draw Walkable Path workflow — nothing touches the backend
  //         until Save is pressed.
  // 'test'  is Test Route — pick two existing points and run the real
  //         Dijkstra endpoint; purely read-only, nothing is ever saved.
  const [mode, setMode] = useState('point');
  const [drawFloor, setDrawFloor] = useState(0);
  const [draftPoints, setDraftPoints] = useState([]);
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [draftError, setDraftError] = useState('');

  const fullMapImageRef = useRef(null);

  const activeMap = useMemo(
    () =>
      maps.find(
        (map) => map.id === selectedMapId,
      ) || null,
    [maps, selectedMapId],
  );

  const adminMapImageUrl =
    activeMap?.sourceImageUrl ||
    activeMap?.imageUrl ||
    activeMap?.displayImageUrl;

  const isProcessing = [
    'pending',
    'processing',
  ].includes(activeMap?.processingStatus);

  const loadMaps = useCallback(
    async (preferredMapId = '') => {
      setIsMapsLoading(true);
      setMapsError('');

      try {
        const normalizedMaps = await getMaps();

        setMaps(normalizedMaps);

        setSelectedMapId((previousId) => {
          if (
            preferredMapId &&
            normalizedMaps.some(
              (map) => map.id === preferredMapId,
            )
          ) {
            return preferredMapId;
          }

          if (
            previousId &&
            normalizedMaps.some(
              (map) => map.id === previousId,
            )
          ) {
            return previousId;
          }

          const currentMap = normalizedMaps.find(
            (map) => map.isCurrent,
          );

          return (
            currentMap?.id ||
            normalizedMaps[0]?.id ||
            ''
          );
        });
      } catch (error) {
        console.error(
          'Failed to load maps:',
          error,
        );

        setMapsError(t.mapsError);
      } finally {
        setIsMapsLoading(false);
      }
    },
    [t.mapsError],
  );

  useEffect(() => {
    loadMaps();
  }, [loadMaps]);

  // Buildings list for the room/store connect-place picker. Loaded once —
  // buildings don't change often enough to warrant reloading per map.
  useEffect(() => {
    const loadBuildingsList = async () => {
      try {
        const data = await getBuildings();
        setBuildingsList(Array.isArray(data) ? data : []);
      } catch (error) {
        console.error('Failed to load buildings for Connect Place:', error);
        setBuildingsList([]);
      }
    };

    loadBuildingsList();
  }, []);

  // Rooms for whichever building is currently selected in the Add Point
  // form's room/store fields.
  useEffect(() => {
    if (!selectedBuildingId) {
      setRoomsList([]);
      return undefined;
    }

    let cancelled = false;

    const loadRoomsForBuilding = async () => {
      setIsRoomsLoading(true);

      try {
        const data = await getRooms({ building_id: selectedBuildingId });
        if (!cancelled) {
          setRoomsList(Array.isArray(data) ? data : []);
        }
      } catch (error) {
        console.error('Failed to load rooms for Connect Place:', error);
        if (!cancelled) setRoomsList([]);
      } finally {
        if (!cancelled) setIsRoomsLoading(false);
      }
    };

    loadRoomsForBuilding();

    return () => {
      cancelled = true;
    };
  }, [selectedBuildingId]);

  // Reusable loader for a single map's RoutePoints + RouteEdges. Used both
  // by the "selected map changed" effect below and after a successful
  // Draw Walkable Path save (to pull in the freshly created graph data).
  const refreshRouteGraph = useCallback(
    async (mapId) => {
      if (!mapId) {
        setRoutePoints([]);
        setRouteEdges([]);
        return;
      }

      setIsPointsLoading(true);
      setIsEdgesLoading(true);
      setPointsError('');
      setEdgesError('');

      const [pointsResult, edgesResult] = await Promise.allSettled([
        getRoutePoints({ map_id: mapId }),
        getRouteEdges({ map_id: mapId }),
      ]);

      if (pointsResult.status === 'fulfilled') {
        setRoutePoints(
          Array.isArray(pointsResult.value) ? pointsResult.value : [],
        );
      } else {
        console.error(
          'Failed to load route points:',
          pointsResult.reason,
        );

        setRoutePoints([]);
        setPointsError(t.pointsError);
      }

      if (edgesResult.status === 'fulfilled') {
        setRouteEdges(
          Array.isArray(edgesResult.value) ? edgesResult.value : [],
        );
      } else {
        console.error(
          'Failed to load route edges:',
          edgesResult.reason,
        );

        setRouteEdges([]);
        setEdgesError(t.edgesError);
      }

      setIsPointsLoading(false);
      setIsEdgesLoading(false);
    },
    [t.pointsError, t.edgesError],
  );

  useEffect(() => {
    let cancelled = false;

    // Switching maps must never leave the previous map's graph on screen,
    // even for a moment — clear points, edges, and any in-progress overlay
    // state before fetching the newly selected map's data. This includes
    // any Draw Walkable Path draft: it is never carried over to another
    // map, and switching away discards it with zero API calls.
    setClickedPoint(null);
    setPointName('');
    setPointType('hallway');
    setFloor(0);
    setFullMapMetrics(null);
    setMode('point');
    setDraftPoints([]);
    setDraftError('');
    setIsSavingDraft(false);
    setSelectedBuildingId('');
    setSelectedRoomId('');
    setTestStartId('');
    setTestEndId('');
    setTestResult(null);
    setTestError('');
    setIsTestLoading(false);

    if (!cancelled) {
      refreshRouteGraph(selectedMapId);
    }

    return () => {
      cancelled = true;
    };
  }, [selectedMapId, refreshRouteGraph]);

  useEffect(() => {
    if (!pollingMapId) return undefined;

    let cancelled = false;
    let timerId;

    const checkStatus = async () => {
      try {
        const statusData = await getMapProcessingStatus(pollingMapId);

        if (cancelled) return;

        setMaps((previousMaps) =>
          previousMaps.map((map) =>
            map.id === pollingMapId
              ? normalizeMap({
                  ...map,
                  processing_status:
                    statusData.processing_status,
                  processing_progress:
                    statusData.processing_progress,
                  processing_error:
                    statusData.processing_error,
                  generation_method:
                    statusData.generation_method,
                  source_image_url:
                    statusData.source_image_url ??
                    map.sourceImageUrl,
                  display_image_url:
                    statusData.display_image_url ??
                    map.displayImageUrl,
                })
              : map,
          ),
        );

        if (
          statusData.processing_status ===
          'completed'
        ) {
          await loadMaps(pollingMapId);
          setPollingMapId('');
          return;
        }

        if (
          statusData.processing_status ===
          'failed'
        ) {
          setPollingMapId('');
          return;
        }

        timerId = window.setTimeout(
          checkStatus,
          1200,
        );
      } catch (error) {
        console.error(
          'Failed to check map processing status:',
          error,
        );

        timerId = window.setTimeout(
          checkStatus,
          2000,
        );
      }
    };

    checkStatus();

    return () => {
      cancelled = true;

      if (timerId) {
        window.clearTimeout(timerId);
      }
    };
  }, [
    loadMaps,
    pollingMapId,
  ]);

  useEffect(() => {
    return () => {
      if (uploadPreview) {
        URL.revokeObjectURL(uploadPreview);
      }
    };
  }, [uploadPreview]);

  const syncFullMapMetrics = () => {
    const image = fullMapImageRef.current;

    if (
      !image?.naturalWidth ||
      !image?.naturalHeight
    ) {
      return;
    }

    const rect = image.getBoundingClientRect();

    setFullMapMetrics({
      displayWidth: rect.width,
      displayHeight: rect.height,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
    });
  };

  useEffect(() => {
    if (!isMapOpen) return undefined;

    const handleResize = () => {
      syncFullMapMetrics();
    };

    window.addEventListener(
      'resize',
      handleResize,
    );

    return () => {
      window.removeEventListener(
        'resize',
        handleResize,
      );
    };
  }, [isMapOpen]);

  const setFormField = (key, value) => {
    setForm((previousForm) => ({
      ...previousForm,
      [key]: value,
    }));
  };

  const setUploadField = (key, value) => {
    setUploadForm((previousForm) => ({
      ...previousForm,
      [key]: value,
    }));
  };

  const handleMapSelection = async (mapId) => {
    setSelectedMapId(mapId);
    setView('detail');
    setIsMapOpen(false);

    if (!mapId) return;

    try {
      const selectedMap = await apiUpdateMap(mapId, {
        is_current: true,
      });

      setMaps((previousMaps) =>
        previousMaps.map((map) =>
          map.id === selectedMap.id
            ? selectedMap
            : {
                ...map,
                isCurrent: false,
              },
        ),
      );
    } catch (error) {
      console.error(
        'Failed to make map current:',
        error,
      );
    }
  };

  const openEdit = () => {
    if (!activeMap) return;

    setForm({
      title: activeMap.title || '',
      campus: activeMap.campus || '',
      address: activeMap.address || '',
      description: activeMap.description || '',
    });

    setView('edit');
  };

  const saveMapDetails = async () => {
    if (!activeMap?.id) return;

    const payload = {
      title: String(form.title || '').trim(),
      campus:
        String(form.campus || '').trim() ||
        null,
      address:
        String(form.address || '').trim() ||
        null,
      description:
        String(form.description || '').trim() ||
        null,
    };

    try {
      const updatedMap = await apiUpdateMap(activeMap.id, payload);

      setMaps((previousMaps) =>
        previousMaps.map((map) =>
          map.id === updatedMap.id
            ? updatedMap
            : map,
        ),
      );

      setView('detail');
    } catch (error) {
      console.error(
        'Failed to update map:',
        error,
      );

      alert('Failed to update map');
    }
  };

  const deleteMap = async () => {
    if (!activeMap?.id) return;

    try {
      await apiDeleteMap(activeMap.id);

      setRoutePoints([]);
      setRouteEdges([]);
      setClickedPoint(null);
      setIsMapOpen(false);
      setView('detail');
      setSelectedMapId('');

      await loadMaps();
    } catch (error) {
      console.error(
        'Failed to delete map:',
        error,
      );

      alert('Failed to delete map');
    }
  };

  const openUploadModal = () => {
    if (uploadPreview) {
      URL.revokeObjectURL(uploadPreview);
    }

    setUploadForm(INITIAL_UPLOAD_FORM);
    setUploadFile(null);
    setUploadPreview('');
    setUploadError('');
    setIsUploadOpen(true);
  };

  const closeUploadModal = () => {
    if (isUploading) return;

    if (uploadPreview) {
      URL.revokeObjectURL(uploadPreview);
    }

    setUploadFile(null);
    setUploadPreview('');
    setUploadError('');
    setIsUploadOpen(false);
  };

  const handleUploadFileChange = (event) => {
    const file =
      event.target.files?.[0] ||
      null;

    if (uploadPreview) {
      URL.revokeObjectURL(uploadPreview);
    }

    setUploadFile(file);
    setUploadError('');

    if (!file) {
      setUploadPreview('');
      return;
    }

    setUploadPreview(
      file.type.startsWith('image/')
        ? URL.createObjectURL(file)
        : '',
    );

    if (!uploadForm.title.trim()) {
      setUploadField(
        'title',
        file.name
          .replace(/\.[^.]+$/, '')
          .replace(/[_-]+/g, ' '),
      );
    }
  };

  const uploadMap = async () => {
    const cleanedTitle =
      uploadForm.title.trim();

    if (
      !uploadFile ||
      cleanedTitle.length < 2
    ) {
      setUploadError(
        t.requiredUploadFields,
      );

      return;
    }

    const scaleNumber = Number(
      uploadForm.scale,
    );

    const safeScale =
      Number.isFinite(scaleNumber) &&
      scaleNumber > 0
        ? scaleNumber
        : 1;

    const formData = new FormData();

    formData.append(
      'file',
      uploadFile,
    );

    formData.append(
      'title',
      cleanedTitle,
    );

    formData.append(
      'scale',
      String(safeScale),
    );

    formData.append(
      'use_openai',
      String(
        Boolean(uploadForm.useOpenAI),
      ),
    );

    if (uploadForm.campus.trim()) {
      formData.append(
        'campus',
        uploadForm.campus.trim(),
      );
    }

    if (uploadForm.address.trim()) {
      formData.append(
        'address',
        uploadForm.address.trim(),
      );
    }

    if (
      uploadForm.description.trim()
    ) {
      formData.append(
        'description',
        uploadForm.description.trim(),
      );
    }

    setIsUploading(true);
    setUploadError('');

    try {
      const newMap = await apiUploadMap(formData);

      setMaps((previousMaps) => [
        newMap,
        ...previousMaps
          .filter(
            (map) => map.id !== newMap.id,
          )
          .map((map) => ({
            ...map,
            isCurrent: false,
          })),
      ]);

      setSelectedMapId(newMap.id);
      setRoutePoints([]);
      setRouteEdges([]);
      setPollingMapId(newMap.id);
      setIsUploadOpen(false);

      if (uploadPreview) {
        URL.revokeObjectURL(
          uploadPreview,
        );
      }

      setUploadFile(null);
      setUploadPreview('');

      alert(t.uploadSuccess);
    } catch (error) {
      console.error(
        'Failed to upload map:',
        error,
      );

      setUploadError(
        error.message ||
          t.uploadError,
      );
    } finally {
      setIsUploading(false);
    }
  };

  const handleFullMapClick = (event) => {
    const image = event.currentTarget;
    const rect =
      image.getBoundingClientRect();

    const displayX =
      event.clientX -
      rect.left;

    const displayY =
      event.clientY -
      rect.top;

    const x = Math.round(
      displayX *
        (image.naturalWidth / rect.width),
    );

    const y = Math.round(
      displayY *
        (image.naturalHeight / rect.height),
    );

    setFullMapMetrics({
      displayWidth: rect.width,
      displayHeight: rect.height,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
    });

    // Draw Walkable Path has its own click handling and must never also
    // trigger the normal single-point Add Point form.
    if (mode === 'draw') {
      handleDrawClick(x, y);
      return;
    }

    setClickedPoint({ x, y });
    setPointName(`Point ${x},${y}`);
  };

  // ── Draw Walkable Path handlers ────────────────────────────────────────────

  const handleDrawClick = (x, y) => {
    setDraftError('');

    // Ignore a click that lands on (or right next to) the last draft point
    // — this is almost always an accidental double-click and would create
    // a zero-length duplicate segment.
    const lastDraftPoint = draftPoints[draftPoints.length - 1];

    if (
      lastDraftPoint &&
      Math.sqrt(
        (x - lastDraftPoint.x) ** 2 + (y - lastDraftPoint.y) ** 2,
      ) <= SNAP_THRESHOLD_PX
    ) {
      return;
    }

    const nearestExisting = findNearestPointWithinThreshold(
      routePoints,
      x,
      y,
      SNAP_THRESHOLD_PX,
      drawFloor,
    );

    if (nearestExisting) {
      const existingId = nearestExisting.id || nearestExisting._id;

      // Reusing the same existing point twice in a row would also create a
      // zero-length segment — ignore it the same way.
      if (lastDraftPoint?.kind === 'existing' && lastDraftPoint.routePointId === existingId) {
        return;
      }

      setDraftPoints((previous) => [
        ...previous,
        {
          tempId: `existing-${existingId}-${previous.length}`,
          kind: 'existing',
          routePointId: existingId,
          x: Number(nearestExisting.x),
          y: Number(nearestExisting.y),
          floor: nearestExisting.floor,
          name: nearestExisting.name,
          point_type: nearestExisting.point_type,
        },
      ]);

      return;
    }

    setDraftPoints((previous) => [
      ...previous,
      {
        tempId: `new-${Date.now()}-${previous.length}`,
        kind: 'new',
        x,
        y,
        floor: drawFloor,
      },
    ]);
  };

  const handleUndoDraft = () => {
    setDraftError('');
    setDraftPoints((previous) => previous.slice(0, -1));
  };

  const handleClearDraft = () => {
    setDraftError('');
    setDraftPoints([]);
  };

  const handleCancelDraw = () => {
    setMode('point');
    setDraftPoints([]);
    setDraftError('');
  };

  const handleSaveDraft = async () => {
    if (draftPoints.length < 2) {
      setDraftError(t.drawNeedTwo);
      return;
    }

    if (!activeMap?.id) {
      setDraftError(t.noSelectedMap);
      return;
    }

    setIsSavingDraft(true);
    setDraftError('');

    // Tracks only what THIS save created, so a failure can be rolled back
    // without ever touching pre-existing reused points.
    const createdPointIds = [];
    const createdEdgeIds = [];

    // resolvedIds[i] is the real backend RoutePoint id for draftPoints[i],
    // whether that point was freshly created or an existing point reused
    // via snapping.
    const resolvedIds = new Array(draftPoints.length).fill(null);

    try {
      for (let i = 0; i < draftPoints.length; i += 1) {
        const draftPoint = draftPoints[i];

        if (draftPoint.kind === 'existing') {
          resolvedIds[i] = draftPoint.routePointId;
          continue;
        }

        const created = await createRoutePoint({
          map_id: activeMap.id,
          name: `Corridor Point ${Date.now()}-${i}`,
          point_type: 'hallway',
          x: draftPoint.x,
          y: draftPoint.y,
          floor: Number(draftPoint.floor ?? drawFloor),
          building_id: null,
          room_id: null,
          is_accessible: true,
        });

        const newId = created.id || created._id;
        resolvedIds[i] = newId;
        createdPointIds.push(newId);
      }

      // Build the set of already-existing edges (in either direction) so a
      // re-drawn segment over an already-connected pair doesn't create a
      // duplicate edge.
      const existingEdgeKeys = new Set(
        routeEdges.map(
          (edge) => `${edge.from_point_id}::${edge.to_point_id}`,
        ),
      );

      routeEdges.forEach((edge) => {
        existingEdgeKeys.add(`${edge.to_point_id}::${edge.from_point_id}`);
      });

      for (let i = 0; i < resolvedIds.length - 1; i += 1) {
        const fromId = resolvedIds[i];
        const toId = resolvedIds[i + 1];

        if (!fromId || !toId || fromId === toId) {
          continue;
        }

        const key = `${fromId}::${toId}`;

        if (existingEdgeKeys.has(key)) {
          continue;
        }

        const createdEdge = await createRouteEdge({
          map_id: activeMap.id,
          from_point_id: fromId,
          to_point_id: toId,
          edge_type: 'walkway',
          is_bidirectional: true,
          is_accessible: true,
        });

        createdEdgeIds.push(createdEdge.id || createdEdge._id);
        existingEdgeKeys.add(key);
        existingEdgeKeys.add(`${toId}::${fromId}`);
      }

      const summary = t.drawSaveSuccess(
        createdPointIds.length,
        createdEdgeIds.length,
      );

      // The draw toolbar unmounts the instant we switch back to 'point'
      // mode, so an inline success message would never actually be seen —
      // use the same alert() pattern the rest of this screen already uses
      // for save confirmations.
      setMode('point');
      setDraftPoints([]);

      await refreshRouteGraph(activeMap.id);

      alert(summary);
    } catch (error) {
      console.error('Failed to save walkable path, rolling back:', error);

      // Roll back edges first (they reference points), then points. Only
      // ever delete what THIS save created — reused existing points are
      // never touched.
      for (const edgeId of createdEdgeIds.reverse()) {
        try {
          await deleteRouteEdge(edgeId);
        } catch (rollbackError) {
          console.error('Rollback: failed to delete edge', edgeId, rollbackError);
        }
      }

      for (const pointId of createdPointIds.reverse()) {
        try {
          await deleteRoutePoint(pointId);
        } catch (rollbackError) {
          console.error('Rollback: failed to delete point', pointId, rollbackError);
        }
      }

      setDraftError(t.drawSaveFailed);

      // Refresh so the overlay reflects the post-rollback truth rather than
      // any partially-created state that briefly existed on the backend.
      await refreshRouteGraph(activeMap.id);
    } finally {
      setIsSavingDraft(false);
    }
  };

  const saveRoutePoint = async () => {
    if (
      !clickedPoint ||
      !pointName.trim()
    ) {
      return;
    }

    if (!activeMap?.id) {
      alert(t.noSelectedMap);
      return;
    }

    const payload = {
      map_id: activeMap.id,
      name: pointName.trim(),
      point_type: pointType,
      x: clickedPoint.x,
      y: clickedPoint.y,
      floor: Number(floor),
      building_id: isPlaceType ? selectedBuildingId || null : null,
      room_id: isPlaceType ? selectedRoomId || null : null,
      is_accessible: true,
    };

    try {
      const savedPoint = await createRoutePoint(payload);

      setRoutePoints(
        (previousPoints) => [
          ...previousPoints,
          savedPoint,
        ],
      );

      // Connect Place: optionally wire this new point into the graph by
      // creating a walkway edge to the nearest existing point on the same
      // floor. Never crosses floors (that would be an invalid walkway) and
      // never crosses maps (routePoints here is already scoped to the
      // active map).
      if (connectToNearest) {
        const nearest = findNearestPointWithinThreshold(
          routePoints,
          savedPoint.x,
          savedPoint.y,
          Infinity,
          savedPoint.floor,
        );

        if (nearest) {
          const nearestId = nearest.id || nearest._id;
          const newId = savedPoint.id || savedPoint._id;

          try {
            const newEdge = await createRouteEdge({
              map_id: activeMap.id,
              from_point_id: newId,
              to_point_id: nearestId,
              edge_type: 'walkway',
              is_bidirectional: true,
              is_accessible: true,
            });

            setRouteEdges((previousEdges) => [...previousEdges, newEdge]);
          } catch (connectError) {
            // The point itself was saved successfully — a failed connecting
            // edge shouldn't be reported as a failed point save. Log it and
            // let the admin connect it manually via Draw Walkable Path.
            console.error(
              'Route point saved, but connecting edge failed:',
              connectError,
            );
          }
        }
      }

      setClickedPoint(null);
      setPointName('');
      setPointType('hallway');
      setFloor(0);
      setSelectedBuildingId('');
      setSelectedRoomId('');

      alert(t.savedPoint);
    } catch (error) {
      console.error(
        'Failed to save route point:',
        error,
      );

      alert(
        'Failed to save route point',
      );
    }
  };

  // ── Test Route mode handlers ────────────────────────────────────────────────
  // Read-only: calls the real Dijkstra endpoint and renders the response.
  // Nothing here is ever written back to MongoDB.

  const handleFindRoute = async () => {
    if (!activeMap?.id || !testStartId || !testEndId) {
      return;
    }

    setIsTestLoading(true);
    setTestError('');
    setTestResult(null);

    try {
      const result = await calculateRoute({
        mapId: activeMap.id,
        startPointId: testStartId,
        endPointId: testEndId,
      });

      setTestResult(result);
    } catch (error) {
      console.error('Failed to calculate test route:', error);
      setTestError(error.message || t.testNoRoute);
    } finally {
      setIsTestLoading(false);
    }
  };

  const handleClearTest = () => {
    setTestResult(null);
    setTestError('');
  };

  const handleChangeTestStart = () => {
    setTestStartId('');
    setTestResult(null);
    setTestError('');
  };

  const handleChangeTestEnd = () => {
    setTestEndId('');
    setTestResult(null);
    setTestError('');
  };

  // ── SVG overlay: point/edge lookups and color coding ──────────────────────
  // The overlay uses a single SVG whose viewBox equals the original image's
  // natural pixel dimensions, so route point x/y and edge geometry can be
  // rendered directly without any manual display-scaling math.

  const pointsById = useMemo(() => {
    const lookup = new Map();

    routePoints.forEach((point) => {
      const id = point.id || point._id;
      if (id) lookup.set(id, point);
    });

    return lookup;
  }, [routePoints]);

  const { resolvedEdges, missingEdgeCount } = useMemo(() => {
    const resolved = [];
    let missingCount = 0;

    routeEdges.forEach((edge) => {
      const fromPoint = pointsById.get(edge.from_point_id);
      const toPoint = pointsById.get(edge.to_point_id);

      if (!fromPoint || !toPoint) {
        missingCount += 1;
        return;
      }

      resolved.push({ edge, fromPoint, toPoint });
    });

    if (missingCount > 0) {
      console.warn(
        `AdminMapScreen: ${missingCount} route edge(s) for map ${selectedMapId} ` +
          'reference a from_point_id/to_point_id that was not found among the ' +
          'loaded route points for this map. These edges were skipped instead ' +
          'of rendered.',
        routeEdges.filter(
          (edge) =>
            !pointsById.has(edge.from_point_id) ||
            !pointsById.has(edge.to_point_id),
        ),
      );
    }

    return { resolvedEdges: resolved, missingEdgeCount: missingCount };
  }, [routeEdges, pointsById, selectedMapId]);

  const POINT_TYPE_COLORS = {
    hallway: '#2f7edb',
    junction: '#8e44ad',
    entrance: '#e6820e',
    room: '#e6820e',
    store: '#e6820e',
    stairs: '#c0392b',
    elevator: '#c0392b',
  };

  const LABELED_POINT_TYPES = new Set(['entrance', 'room', 'store']);
  const VERTICAL_TRANSIT_TYPES = new Set(['stairs', 'elevator']);

  const getPointColor = (pointType) =>
    POINT_TYPE_COLORS[pointType] || '#5f7fa6';

  const getEdgeStyle = (edgeType) => {
    if (VERTICAL_TRANSIT_TYPES.has(edgeType)) {
      return { stroke: '#c0392b', dash: '7 5' };
    }

    return { stroke: '#a9c3e3', dash: undefined };
  };

  return (
    <div className="layout-wrapper">
      <div
        className="layout-shell adm-shell"
        dir={isRTL ? 'rtl' : 'ltr'}
      >
        <div className="adm-inner-header">
          <div className="adm-topbar">
            <button
              className={`adm-back-btn${
                isRTL
                  ? ' adm-back-btn-rtl'
                  : ''
              }`}
              onClick={() =>
                navigate('/screen/05')
              }
            >
              <BackArrow flip={isRTL} />
              {t.back}
            </button>

            <div
              className="adm-lang-pill"
              role="group"
            >
              {LANGUAGES.map(
                (language) => (
                  <button
                    key={language.code}
                    className={`adm-lang-btn${
                      lang === language.code
                        ? ' active'
                        : ''
                    }`}
                    onClick={() =>
                      setLang(
                        language.code,
                      )
                    }
                  >
                    {language.label}
                  </button>
                ),
              )}
            </div>
          </div>

          <div className="adm-inner-heading">
            <div className="adm-inner-icon">
              <MapIcon />
            </div>

            <h1 className="adm-inner-title">
              {t.title}
            </h1>
          </div>
        </div>

        <div className="adm-content">
          {view === 'detail' && (
            <>
              <div
                className="adm-form-card"
                style={{
                  marginBottom: 16,
                }}
              >
                <div
                  className="adm-form-group"
                  style={{
                    marginBottom: 0,
                  }}
                >
                  <label className="adm-form-label">
                    {t.selectMap}
                  </label>

                  <select
                    className="adm-form-input"
                    value={selectedMapId}
                    disabled={
                      isMapsLoading ||
                      maps.length === 0
                    }
                    onChange={(event) =>
                      handleMapSelection(
                        event.target.value,
                      )
                    }
                  >
                    {maps.length === 0 && (
                      <option value="">
                        {t.noSelectedMap}
                      </option>
                    )}

                    {maps.map((map) => (
                      <option
                        key={map.id}
                        value={map.id}
                      >
                        {map.title || map.id}

                        {map.isCurrent
                          ? ` — ${t.current}`
                          : ''}
                      </option>
                    ))}
                  </select>
                </div>

                <div
                  style={{
                    marginTop: 10,
                    fontSize: 12.5,
                    color: mapsError
                      ? '#c0392b'
                      : '#5f7fa6',
                  }}
                >
                  {isMapsLoading
                    ? t.loadingMaps
                    : mapsError ||
                      `${t.savedPoints}: ${routePoints.length}`}
                </div>

                {isPointsLoading && (
                  <div
                    style={{
                      marginTop: 6,
                      fontSize: 12.5,
                      color: '#5f7fa6',
                    }}
                  >
                    {t.loadingPoints}
                  </div>
                )}

                {!isPointsLoading &&
                  pointsError && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12.5,
                        color: '#c0392b',
                      }}
                    >
                      {pointsError}
                    </div>
                  )}

                {!isPointsLoading &&
                  !pointsError &&
                  selectedMapId &&
                  routePoints.length ===
                    0 && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12.5,
                        color: '#7a9abf',
                      }}
                    >
                      {t.noPoints}
                    </div>
                  )}

                {isEdgesLoading && (
                  <div
                    style={{
                      marginTop: 6,
                      fontSize: 12.5,
                      color: '#5f7fa6',
                    }}
                  >
                    {t.loadingEdges}
                  </div>
                )}

                {!isEdgesLoading &&
                  edgesError && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12.5,
                        color: '#c0392b',
                      }}
                    >
                      {edgesError}
                    </div>
                  )}

                {!isEdgesLoading &&
                  !edgesError &&
                  selectedMapId && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12.5,
                        color:
                          routeEdges.length === 0
                            ? '#7a9abf'
                            : '#5f7fa6',
                      }}
                    >
                      {routeEdges.length === 0
                        ? t.noEdges
                        : `${t.savedEdges}: ${routeEdges.length}`}
                    </div>
                  )}

                {missingEdgeCount > 0 && (
                  <div
                    style={{
                      marginTop: 6,
                      fontSize: 12.5,
                      color: '#c0392b',
                    }}
                  >
                    {missingEdgeCount} {t.edgeDataWarning}
                  </div>
                )}
              </div>

              {isProcessing && (
                <div
                  className="adm-form-card"
                  style={{
                    marginBottom: 16,
                  }}
                >
                  <div
                    style={{
                      fontWeight: 800,
                      color: '#173b70',
                      marginBottom: 8,
                    }}
                  >
                    {t.processing}:{' '}
                    {activeMap?.processingProgress ||
                      0}
                    %
                  </div>

                  <div
                    style={{
                      width: '100%',
                      height: 10,
                      background: '#e5eef9',
                      borderRadius: 999,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        width: `${Math.max(
                          3,
                          Math.min(
                            100,
                            activeMap?.processingProgress ||
                              0,
                          ),
                        )}%`,
                        height: '100%',
                        background: '#376fbd',
                        transition:
                          'width 0.3s ease',
                      }}
                    />
                  </div>
                </div>
              )}

              {activeMap?.processingStatus ===
                'failed' && (
                <div
                  className="adm-form-card"
                  style={{
                    marginBottom: 16,
                    color: '#c0392b',
                  }}
                >
                  <div
                    style={{
                      fontWeight: 800,
                    }}
                  >
                    {t.processingFailed}
                  </div>

                  {activeMap.processingError && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12,
                      }}
                    >
                      {
                        activeMap.processingError
                      }
                    </div>
                  )}
                </div>
              )}

              <div className="adm-map-img-placeholder">
                {activeMap?.hasImage &&
                adminMapImageUrl ? (
                  <>
                    <img
                      src={adminMapImageUrl}
                      alt={
                        activeMap.title ||
                        'Selected map'
                      }
                      onClick={() =>
                        setIsMapOpen(true)
                      }
                      style={{
                        display: 'block',
                        width: '100%',
                        maxHeight: '520px',
                        objectFit: 'contain',
                        borderRadius: '18px',
                        cursor: 'zoom-in',
                      }}
                    />

                    <div
                      style={{
                        marginTop: 10,
                        fontSize: 12,
                        fontWeight: 700,
                        color: '#4c7bb5',
                      }}
                    >
                      {t.openFullMap}
                    </div>
                  </>
                ) : (
                  <>
                    <MapIcon />

                    <div className="adm-map-img-label">
                      {isProcessing
                        ? t.processing
                        : t.noMap}
                    </div>

                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12,
                        color: '#7a9abf',
                      }}
                    >
                      {isProcessing
                        ? `${
                            activeMap?.processingProgress ||
                            0
                          }%`
                        : t.noMapHint}
                    </div>
                  </>
                )}
              </div>

              <button
                className="adm-upload-btn"
                onClick={openUploadModal}
              >
                <UploadIcon />
                {t.uploadNewMap}
              </button>

              <div className="adm-btn-row">
                <button
                  className="adm-btn adm-btn-secondary"
                  onClick={openEdit}
                  disabled={!activeMap?.id}
                >
                  <EditIcon />
                  {t.editDetails}
                </button>

                <button
                  className="adm-btn adm-btn-danger"
                  onClick={() =>
                    setView(
                      'confirm-delete',
                    )
                  }
                  disabled={!activeMap?.id}
                >
                  <DeleteIcon />
                  {t.deleteMap}
                </button>
              </div>

              <div className="adm-section-row">
                <span className="adm-section-lbl">
                  {t.selectedMap}
                </span>
              </div>

              <div className="adm-form-card">
                <div className="adm-detail-list">
                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {t.details.title}
                    </span>

                    <span className="adm-detail-val">
                      {activeMap?.title ||
                        '—'}
                    </span>
                  </div>

                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {t.details.campus}
                    </span>

                    <span className="adm-detail-val">
                      {activeMap?.campus ||
                        '—'}
                    </span>
                  </div>

                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {t.details.address}
                    </span>

                    <span className="adm-detail-val">
                      {activeMap?.address ||
                        '—'}
                    </span>
                  </div>

                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {
                        t.details
                          .description
                      }
                    </span>

                    <span className="adm-detail-val">
                      {activeMap?.description ||
                        '—'}
                    </span>
                  </div>

                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {t.details.status}
                    </span>

                    <span className="adm-detail-val">
                      {activeMap?.processingStatus ||
                        '—'}
                    </span>
                  </div>

                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {t.details.mapId}
                    </span>

                    <span
                      className="adm-detail-val"
                      style={{
                        wordBreak: 'break-all',
                        fontSize: 11.5,
                      }}
                    >
                      {activeMap?.id || '—'}
                    </span>
                  </div>
                </div>
              </div>
            </>
          )}

          {view === 'edit' && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">
                {t.editTitle}
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.mapTitle}
                </label>

                <input
                  className="adm-form-input"
                  value={form.title || ''}
                  onChange={(event) =>
                    setFormField(
                      'title',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.campus}
                </label>

                <input
                  className="adm-form-input"
                  value={form.campus || ''}
                  onChange={(event) =>
                    setFormField(
                      'campus',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.address}
                </label>

                <input
                  className="adm-form-input"
                  value={form.address || ''}
                  onChange={(event) =>
                    setFormField(
                      'address',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.description}
                </label>

                <textarea
                  className="adm-form-textarea"
                  value={
                    form.description || ''
                  }
                  onChange={(event) =>
                    setFormField(
                      'description',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-actions">
                <button
                  className="adm-btn adm-btn-cancel"
                  onClick={() =>
                    setView('detail')
                  }
                >
                  {t.cancel}
                </button>

                <button
                  className="adm-btn adm-btn-primary"
                  onClick={saveMapDetails}
                >
                  {t.saveChanges}
                </button>
              </div>
            </div>
          )}

          {view ===
            'confirm-delete' && (
            <div
              className="adm-form-card"
              style={{
                textAlign: 'center',
                padding: '28px 20px',
              }}
            >
              <div
                style={{
                  color: '#c0392b',
                  marginBottom: 12,
                }}
              >
                <DeleteIcon />
              </div>

              <div
                style={{
                  fontFamily:
                    'var(--font-brand)',
                  fontSize: 16,
                  fontWeight: 700,
                  color: '#1a3a6b',
                  marginBottom: 8,
                }}
              >
                {t.confirmDelete}
              </div>

              <div
                style={{
                  fontSize: 12.5,
                  color: '#7a9abf',
                  marginBottom: 20,
                }}
              >
                {activeMap?.title}
              </div>

              <div
                className="adm-form-actions"
                style={{
                  justifyContent: 'center',
                }}
              >
                <button
                  className="adm-btn adm-btn-cancel"
                  onClick={() =>
                    setView('detail')
                  }
                >
                  {t.cancel}
                </button>

                <button
                  className="adm-btn adm-btn-confirm-delete"
                  onClick={deleteMap}
                >
                  {t.yesDelete}
                </button>
              </div>
            </div>
          )}
        </div>

        {isUploadOpen && (
          <div
            onClick={closeUploadModal}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 10020,
              background:
                'rgba(9, 26, 53, 0.78)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 20,
              overflowY: 'auto',
            }}
          >
            <div
              className="adm-form-card"
              onClick={(event) =>
                event.stopPropagation()
              }
              style={{
                width:
                  'min(560px, 96vw)',
                maxHeight: '92vh',
                overflowY: 'auto',
                padding: 24,
              }}
            >
              <div className="adm-form-card-title">
                {t.uploadTitle}
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.chooseFile}
                </label>

                <input
                  className="adm-form-input"
                  type="file"
                  accept="image/png,image/jpeg,image/jpg,image/webp,application/pdf,.pdf"
                  onChange={
                    handleUploadFileChange
                  }
                />
              </div>

              {uploadFile && (
                <div
                  style={{
                    marginBottom: 14,
                    padding: 12,
                    borderRadius: 12,
                    background: '#f1f6fc',
                    color: '#315b8f',
                    fontSize: 12.5,
                    wordBreak: 'break-word',
                  }}
                >
                  <strong>
                    {t.selectedFile}:
                  </strong>{' '}
                  {uploadFile.name}
                </div>
              )}

              {uploadPreview && (
                <img
                  src={uploadPreview}
                  alt="Map preview"
                  style={{
                    display: 'block',
                    width: '100%',
                    maxHeight: 230,
                    objectFit: 'contain',
                    borderRadius: 14,
                    background: '#eef4fb',
                    marginBottom: 16,
                  }}
                />
              )}

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.mapTitle}
                </label>

                <input
                  className="adm-form-input"
                  value={uploadForm.title}
                  onChange={(event) =>
                    setUploadField(
                      'title',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.campus}
                </label>

                <input
                  className="adm-form-input"
                  value={uploadForm.campus}
                  onChange={(event) =>
                    setUploadField(
                      'campus',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.address}
                </label>

                <input
                  className="adm-form-input"
                  value={uploadForm.address}
                  onChange={(event) =>
                    setUploadField(
                      'address',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.description}
                </label>

                <textarea
                  className="adm-form-textarea"
                  value={
                    uploadForm.description
                  }
                  onChange={(event) =>
                    setUploadField(
                      'description',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.scale}
                </label>

                <input
                  className="adm-form-input"
                  type="number"
                  min="0.0001"
                  step="0.01"
                  value={uploadForm.scale}
                  onChange={(event) =>
                    setUploadField(
                      'scale',
                      event.target.value,
                    )
                  }
                />
              </div>

              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 9,
                  marginBottom: 16,
                  color: '#315b8f',
                  fontSize: 13,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                <input
                  type="checkbox"
                  checked={
                    uploadForm.useOpenAI
                  }
                  onChange={(event) =>
                    setUploadField(
                      'useOpenAI',
                      event.target.checked,
                    )
                  }
                />

                {t.useOpenAI}
              </label>

              {uploadError && (
                <div
                  style={{
                    marginBottom: 14,
                    padding: 11,
                    borderRadius: 10,
                    background: '#fff0f0',
                    color: '#b42318',
                    fontSize: 12.5,
                    fontWeight: 700,
                  }}
                >
                  {uploadError}
                </div>
              )}

              <div className="adm-form-actions">
                <button
                  className="adm-btn adm-btn-cancel"
                  onClick={closeUploadModal}
                  disabled={isUploading}
                >
                  {t.cancel}
                </button>

                <button
                  className="adm-btn adm-btn-primary"
                  onClick={uploadMap}
                  disabled={isUploading}
                >
                  {isUploading
                    ? t.uploading
                    : t.upload}
                </button>
              </div>
            </div>
          </div>
        )}

        {isMapOpen &&
          adminMapImageUrl && (
            <div
              onClick={() =>
                setIsMapOpen(false)
              }
              style={{
                position: 'fixed',
                inset: 0,
                background:
                  'rgba(0, 0, 0, 0.82)',
                zIndex: 9999,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: 24,
              }}
            >
              <div
                onClick={(event) =>
                  event.stopPropagation()
                }
                style={{
                  position: 'relative',
                  maxWidth: '96vw',
                  maxHeight: '90vh',
                }}
              >
                <img
                  ref={fullMapImageRef}
                  src={adminMapImageUrl}
                  alt={
                    activeMap?.title ||
                    'Full map'
                  }
                  onLoad={
                    syncFullMapMetrics
                  }
                  onClick={
                    handleFullMapClick
                  }
                  style={{
                    display: 'block',
                    maxWidth: '96vw',
                    maxHeight: '90vh',
                    objectFit: 'contain',
                    borderRadius: 14,
                    background: 'white',
                    cursor: 'crosshair',
                  }}
                />

                {fullMapMetrics &&
                  (() => {
                    const radius = Math.max(
                      8,
                      fullMapMetrics.naturalWidth * 0.006,
                    );

                    return (
                      <svg
                        viewBox={`0 0 ${fullMapMetrics.naturalWidth} ${fullMapMetrics.naturalHeight}`}
                        preserveAspectRatio="xMidYMid meet"
                        style={{
                          position: 'absolute',
                          inset: 0,
                          width: '100%',
                          height: '100%',
                          pointerEvents: 'none',
                        }}
                      >
                        {/* Route edges — drawn first so points sit on top */}
                        {resolvedEdges.map(
                          ({ edge, fromPoint, toPoint }) => {
                            const style = getEdgeStyle(
                              edge.edge_type,
                            );

                            return (
                              <line
                                key={edge.id || edge._id}
                                x1={fromPoint.x}
                                y1={fromPoint.y}
                                x2={toPoint.x}
                                y2={toPoint.y}
                                stroke={style.stroke}
                                strokeWidth={
                                  Math.max(
                                    2,
                                    fullMapMetrics.naturalWidth * 0.0015,
                                  )
                                }
                                strokeDasharray={style.dash}
                                strokeLinecap="round"
                              />
                            );
                          },
                        )}

                        {/* Existing saved route points */}
                        {routePoints.map((point) => {
                          const pointX = Number(point.x);
                          const pointY = Number(point.y);

                          if (
                            !Number.isFinite(pointX) ||
                            !Number.isFinite(pointY)
                          ) {
                            return null;
                          }

                          const isVertical = VERTICAL_TRANSIT_TYPES.has(
                            point.point_type,
                          );

                          const color = getPointColor(
                            point.point_type,
                          );

                          const key =
                            point.id ||
                            point._id ||
                            `${point.x}-${point.y}-${point.name}`;

                          return (
                            <g key={key}>
                              {isVertical ? (
                                <rect
                                  x={pointX - radius}
                                  y={pointY - radius}
                                  width={radius * 2}
                                  height={radius * 2}
                                  fill={color}
                                  stroke="white"
                                  strokeWidth={radius * 0.25}
                                  transform={`rotate(45 ${pointX} ${pointY})`}
                                />
                              ) : (
                                <circle
                                  cx={pointX}
                                  cy={pointY}
                                  r={radius}
                                  fill={color}
                                  stroke="white"
                                  strokeWidth={radius * 0.25}
                                />
                              )}

                              {LABELED_POINT_TYPES.has(
                                point.point_type,
                              ) &&
                                point.name && (
                                  <text
                                    x={pointX}
                                    y={pointY - radius - 6}
                                    textAnchor="middle"
                                    fontSize={
                                      fullMapMetrics.naturalWidth * 0.012
                                    }
                                    fontWeight="700"
                                    fill="#173b70"
                                    stroke="white"
                                    strokeWidth={2}
                                    paintOrder="stroke"
                                  >
                                    {point.name}
                                  </text>
                                )}
                            </g>
                          );
                        })}

                        {/* Test Route result — visually distinct from normal graph edges:
                            solid, thick, bright green vs. the light blue/red dashed
                            edges used for the real graph. */}
                        {mode === 'test' &&
                          testResult &&
                          (() => {
                            const testPathPoints = (
                              testResult.path_point_ids || []
                            )
                              .map((id) => pointsById.get(id))
                              .filter(Boolean);

                            if (testPathPoints.length < 2) return null;

                            return (
                              <>
                                <polyline
                                  points={testPathPoints
                                    .map((p) => `${p.x},${p.y}`)
                                    .join(' ')}
                                  fill="none"
                                  stroke="#16a34a"
                                  strokeWidth={Math.max(
                                    3,
                                    fullMapMetrics.naturalWidth * 0.0025,
                                  )}
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                                {testPathPoints.map((p, index) => (
                                  <circle
                                    key={`test-${p.id || p._id || index}`}
                                    cx={p.x}
                                    cy={p.y}
                                    r={radius * 0.7}
                                    fill="#16a34a"
                                    stroke="white"
                                    strokeWidth={radius * 0.2}
                                  />
                                ))}
                              </>
                            );
                          })()}

                        {/* In-progress clicked point (not yet saved) — Add Point mode only */}
                        {mode === 'point' &&
                          clickedPoint &&
                          Number.isFinite(Number(clickedPoint.x)) &&
                          Number.isFinite(Number(clickedPoint.y)) && (
                            <circle
                              cx={clickedPoint.x}
                              cy={clickedPoint.y}
                              r={radius * 1.15}
                              fill="red"
                              stroke="white"
                              strokeWidth={radius * 0.3}
                            />
                          )}

                        {/* Draw Walkable Path draft — live polyline + draft points */}
                        {mode === 'draw' && draftPoints.length > 1 && (
                          <polyline
                            points={draftPoints
                              .map((point) => `${point.x},${point.y}`)
                              .join(' ')}
                            fill="none"
                            stroke="#f2b705"
                            strokeWidth={Math.max(
                              2,
                              fullMapMetrics.naturalWidth * 0.0018,
                            )}
                            strokeDasharray="10 6"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        )}

                        {mode === 'draw' &&
                          draftPoints.map((point, index) => (
                            <g key={point.tempId}>
                              {point.kind === 'existing' && (
                                <circle
                                  cx={point.x}
                                  cy={point.y}
                                  r={radius * 1.6}
                                  fill="none"
                                  stroke="#2ecc71"
                                  strokeWidth={radius * 0.35}
                                />
                              )}
                              <circle
                                cx={point.x}
                                cy={point.y}
                                r={radius * 0.85}
                                fill={
                                  point.kind === 'existing'
                                    ? '#2ecc71'
                                    : '#f2b705'
                                }
                                stroke="white"
                                strokeWidth={radius * 0.22}
                              />
                              <text
                                x={point.x}
                                y={point.y - radius * 1.9}
                                textAnchor="middle"
                                fontSize={fullMapMetrics.naturalWidth * 0.011}
                                fontWeight="700"
                                fill="#173b70"
                                stroke="white"
                                strokeWidth={2}
                                paintOrder="stroke"
                              >
                                {index + 1}
                              </text>
                            </g>
                          ))}
                      </svg>
                    );
                  })()}

                {/* ── Mode toolbar: Add Point / Draw Walkable Path ── */}
                <div
                  style={{
                    position: 'absolute',
                    top: 20,
                    left: '50%',
                    transform: 'translateX(-50%)',
                    display: 'flex',
                    gap: 8,
                    background: 'rgba(20, 55, 105, 0.92)',
                    padding: 6,
                    borderRadius: 999,
                  }}
                >
                  <button
                    type="button"
                    onClick={() => {
                      if (mode !== 'point') {
                        setMode('point');
                        setDraftPoints([]);
                        setDraftError('');
                      }
                    }}
                    style={{
                      border: 'none',
                      borderRadius: 999,
                      padding: '8px 16px',
                      fontSize: 12.5,
                      fontWeight: 700,
                      cursor: 'pointer',
                      background: mode === 'point' ? 'white' : 'transparent',
                      color: mode === 'point' ? '#173b70' : 'white',
                    }}
                  >
                    {t.addPointMode}
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      if (mode !== 'draw') {
                        setMode('draw');
                        setClickedPoint(null);
                        setPointName('');
                      }
                    }}
                    style={{
                      border: 'none',
                      borderRadius: 999,
                      padding: '8px 16px',
                      fontSize: 12.5,
                      fontWeight: 700,
                      cursor: 'pointer',
                      background: mode === 'draw' ? 'white' : 'transparent',
                      color: mode === 'draw' ? '#173b70' : 'white',
                    }}
                  >
                    {t.drawMode}
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      if (mode !== 'test') {
                        setMode('test');
                        setClickedPoint(null);
                        setPointName('');
                      }
                    }}
                    style={{
                      border: 'none',
                      borderRadius: 999,
                      padding: '8px 16px',
                      fontSize: 12.5,
                      fontWeight: 700,
                      cursor: 'pointer',
                      background: mode === 'test' ? 'white' : 'transparent',
                      color: mode === 'test' ? '#173b70' : 'white',
                    }}
                  >
                    {t.testMode}
                  </button>
                </div>

                {mode === 'point' && (
                  <div
                    style={{
                      position: 'absolute',
                      left: '50%',
                      bottom: 18,
                      transform:
                        'translateX(-50%)',
                      background:
                        'rgba(20, 55, 105, 0.92)',
                      color: 'white',
                      padding: '10px 16px',
                      borderRadius: 999,
                      fontSize: 13,
                      fontWeight: 700,
                      pointerEvents: 'none',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {t.selectPoint}
                  </div>
                )}

                {mode === 'draw' && (
                  <div
                    style={{
                      position: 'absolute',
                      top: 76,
                      left: 20,
                      width: 300,
                      background: 'white',
                      borderRadius: 16,
                      padding: 16,
                      boxShadow: '0 14px 40px rgba(0, 0, 0, 0.35)',
                    }}
                  >
                    <div
                      style={{
                        fontWeight: 800,
                        color: '#173b70',
                        marginBottom: 8,
                      }}
                    >
                      {t.drawMode}
                    </div>

                    <div
                      style={{
                        fontSize: 12,
                        color: '#5f7fa6',
                        marginBottom: 10,
                      }}
                    >
                      {t.drawHint}
                    </div>

                    <div className="adm-form-group">
                      <label className="adm-form-label">{t.drawFloor}</label>
                      <input
                        className="adm-form-input"
                        type="number"
                        value={drawFloor}
                        disabled={isSavingDraft}
                        onChange={(event) =>
                          setDrawFloor(Number(event.target.value))
                        }
                      />
                    </div>

                    <div
                      style={{
                        fontSize: 12.5,
                        fontWeight: 700,
                        color: '#173b70',
                        marginBottom: 10,
                      }}
                    >
                      {t.drawPointCount(draftPoints.length)}
                    </div>

                    {draftError && (
                      <div
                        style={{
                          marginBottom: 10,
                          padding: 8,
                          borderRadius: 10,
                          background: '#fff0f0',
                          color: '#b42318',
                          fontSize: 12,
                          fontWeight: 700,
                        }}
                      >
                        {draftError}
                      </div>
                    )}

                    <div
                      className="adm-form-actions"
                      style={{ flexWrap: 'wrap', gap: 8 }}
                    >
                      <button
                        type="button"
                        className="adm-btn adm-btn-cancel"
                        disabled={isSavingDraft || draftPoints.length === 0}
                        onClick={handleUndoDraft}
                      >
                        {t.drawUndo}
                      </button>

                      <button
                        type="button"
                        className="adm-btn adm-btn-cancel"
                        disabled={isSavingDraft || draftPoints.length === 0}
                        onClick={handleClearDraft}
                      >
                        {t.drawClear}
                      </button>

                      <button
                        type="button"
                        className="adm-btn adm-btn-cancel"
                        disabled={isSavingDraft}
                        onClick={handleCancelDraw}
                      >
                        {t.drawCancel}
                      </button>

                      <button
                        type="button"
                        className="adm-btn adm-btn-primary"
                        disabled={isSavingDraft || draftPoints.length < 2}
                        onClick={handleSaveDraft}
                      >
                        {isSavingDraft ? t.drawSaving : t.drawSave}
                      </button>
                    </div>
                  </div>
                )}

                {mode === 'test' && (
                  <div
                    style={{
                      position: 'absolute',
                      top: 76,
                      left: 20,
                      width: 300,
                      background: 'white',
                      borderRadius: 16,
                      padding: 16,
                      boxShadow: '0 14px 40px rgba(0, 0, 0, 0.35)',
                    }}
                  >
                    <div
                      style={{
                        fontWeight: 800,
                        color: '#173b70',
                        marginBottom: 10,
                      }}
                    >
                      {t.testMode}
                    </div>

                    {!testStartId ? (
                      <div className="adm-form-group">
                        <label className="adm-form-label">
                          {t.testStart}
                        </label>
                        <select
                          className="adm-form-input"
                          value=""
                          onChange={(event) =>
                            setTestStartId(event.target.value)
                          }
                        >
                          <option value="">{t.testSelectStart}</option>
                          {routePoints.map((point) => (
                            <option
                              key={point.id || point._id}
                              value={point.id || point._id}
                            >
                              {point.name} ({point.point_type})
                            </option>
                          ))}
                        </select>
                      </div>
                    ) : (
                      <div
                        style={{
                          marginBottom: 10,
                          fontSize: 12.5,
                          color: '#173b70',
                        }}
                      >
                        <strong>{t.testStart}:</strong>{' '}
                        {
                          routePoints.find(
                            (point) =>
                              (point.id || point._id) === testStartId,
                          )?.name
                        }{' '}
                        <button
                          type="button"
                          onClick={handleChangeTestStart}
                          style={{
                            border: 'none',
                            background: 'none',
                            color: '#4a7ac8',
                            fontWeight: 700,
                            cursor: 'pointer',
                            fontSize: 11.5,
                          }}
                        >
                          {t.testChangeStart}
                        </button>
                      </div>
                    )}

                    {!testEndId ? (
                      <div className="adm-form-group">
                        <label className="adm-form-label">
                          {t.testEnd}
                        </label>
                        <select
                          className="adm-form-input"
                          value=""
                          onChange={(event) =>
                            setTestEndId(event.target.value)
                          }
                        >
                          <option value="">{t.testSelectEnd}</option>
                          {routePoints.map((point) => (
                            <option
                              key={point.id || point._id}
                              value={point.id || point._id}
                            >
                              {point.name} ({point.point_type})
                            </option>
                          ))}
                        </select>
                      </div>
                    ) : (
                      <div
                        style={{
                          marginBottom: 10,
                          fontSize: 12.5,
                          color: '#173b70',
                        }}
                      >
                        <strong>{t.testEnd}:</strong>{' '}
                        {
                          routePoints.find(
                            (point) =>
                              (point.id || point._id) === testEndId,
                          )?.name
                        }{' '}
                        <button
                          type="button"
                          onClick={handleChangeTestEnd}
                          style={{
                            border: 'none',
                            background: 'none',
                            color: '#4a7ac8',
                            fontWeight: 700,
                            cursor: 'pointer',
                            fontSize: 11.5,
                          }}
                        >
                          {t.testChangeEnd}
                        </button>
                      </div>
                    )}

                    {testError && (
                      <div
                        style={{
                          marginBottom: 10,
                          padding: 8,
                          borderRadius: 10,
                          background: '#fff0f0',
                          color: '#b42318',
                          fontSize: 12,
                          fontWeight: 700,
                        }}
                      >
                        {testError}
                      </div>
                    )}

                    {testResult && (
                      <div
                        style={{
                          marginBottom: 10,
                          padding: 8,
                          borderRadius: 10,
                          background: '#eafaf0',
                          color: '#1a7f37',
                          fontSize: 12,
                          fontWeight: 700,
                        }}
                      >
                        {t.testDistance(testResult.total_distance)}
                        <br />
                        {t.testStepCount(
                          (testResult.path_point_ids || []).length,
                        )}
                      </div>
                    )}

                    <div
                      className="adm-form-actions"
                      style={{ flexWrap: 'wrap', gap: 8 }}
                    >
                      <button
                        type="button"
                        className="adm-btn adm-btn-cancel"
                        disabled={!testResult && !testError}
                        onClick={handleClearTest}
                      >
                        {t.testClear}
                      </button>

                      <button
                        type="button"
                        className="adm-btn adm-btn-primary"
                        disabled={
                          isTestLoading || !testStartId || !testEndId
                        }
                        onClick={handleFindRoute}
                      >
                        {isTestLoading ? t.testCalculating : t.testFind}
                      </button>
                    </div>
                  </div>
                )}

                {mode === 'point' && clickedPoint && (
                  <div
                    style={{
                      position: 'absolute',
                      top: 20,
                      left: 20,
                      width: 300,
                      background: 'white',
                      borderRadius: 16,
                      padding: 16,
                      boxShadow:
                        '0 14px 40px rgba(0, 0, 0, 0.35)',
                    }}
                  >
                    <div
                      style={{
                        fontWeight: 800,
                        color: '#173b70',
                        marginBottom: 10,
                      }}
                    >
                      {t.addPoint}
                    </div>

                    <div
                      style={{
                        fontWeight: 700,
                        color: '#173b70',
                        marginBottom: 10,
                      }}
                    >
                      X: {clickedPoint.x} |
                      Y: {clickedPoint.y}
                    </div>

                    <div className="adm-form-group">
                      <label className="adm-form-label">
                        {t.pointName}
                      </label>

                      <input
                        className="adm-form-input"
                        value={pointName}
                        onChange={(event) =>
                          setPointName(
                            event.target
                              .value,
                          )
                        }
                      />
                    </div>

                    <div className="adm-form-group">
                      <label className="adm-form-label">
                        {t.pointType}
                      </label>

                      <select
                        className="adm-form-input"
                        value={pointType}
                        onChange={(event) =>
                          setPointType(
                            event.target
                              .value,
                          )
                        }
                      >
                        <option value="entrance">
                          entrance
                        </option>

                        <option value="hallway">
                          hallway
                        </option>

                        <option value="junction">
                          junction
                        </option>

                        <option value="stairs">
                          stairs
                        </option>

                        <option value="elevator">
                          elevator
                        </option>

                        <option value="room">
                          room
                        </option>

                        <option value="store">
                          store
                        </option>
                      </select>
                    </div>

                    {isPlaceType && (
                      <>
                        <div className="adm-form-group">
                          <label className="adm-form-label">
                            {t.building}
                          </label>

                          <select
                            className="adm-form-input"
                            value={selectedBuildingId}
                            onChange={(event) => {
                              setSelectedBuildingId(event.target.value);
                              setSelectedRoomId('');
                            }}
                          >
                            <option value="">{t.selectBuilding}</option>
                            {buildingsList.map((building) => (
                              <option key={building.id} value={building.id}>
                                {building.name_en || building.id}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div className="adm-form-group">
                          <label className="adm-form-label">
                            {t.room}
                          </label>

                          <select
                            className="adm-form-input"
                            value={selectedRoomId}
                            disabled={
                              !selectedBuildingId || isRoomsLoading
                            }
                            onChange={(event) =>
                              setSelectedRoomId(event.target.value)
                            }
                          >
                            <option value="">{t.selectRoom}</option>
                            {roomsList.map((room) => (
                              <option key={room.id} value={room.id}>
                                {room.name_en || room.id}
                              </option>
                            ))}
                          </select>

                          {selectedRoomId &&
                            (() => {
                              const alreadyLinked = routePoints.find(
                                (point) => point.room_id === selectedRoomId,
                              );

                              if (!alreadyLinked) return null;

                              return (
                                <div
                                  style={{
                                    marginTop: 6,
                                    fontSize: 11.5,
                                    color: '#b47b09',
                                  }}
                                >
                                  {t.roomAlreadyLinked(alreadyLinked.name)}
                                </div>
                              );
                            })()}
                        </div>
                      </>
                    )}

                    <div className="adm-form-group">
                      <label className="adm-form-label">
                        {t.floor}
                      </label>

                      <input
                        className="adm-form-input"
                        type="number"
                        value={floor}
                        onChange={(event) =>
                          setFloor(
                            event.target
                              .value,
                          )
                        }
                      />
                    </div>

                    <label
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        marginBottom: 14,
                        fontSize: 12.5,
                        fontWeight: 700,
                        color: '#315b8f',
                        cursor: 'pointer',
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={connectToNearest}
                        onChange={(event) =>
                          setConnectToNearest(event.target.checked)
                        }
                      />
                      {t.connectNearest}
                    </label>

                    <div className="adm-form-actions">
                      <button
                        className="adm-btn adm-btn-cancel"
                        onClick={() => {
                          setClickedPoint(
                            null,
                          );

                          setPointName('');
                          setSelectedBuildingId('');
                          setSelectedRoomId('');
                        }}
                      >
                        {t.cancel}
                      </button>

                      <button
                        className="adm-btn adm-btn-primary"
                        onClick={
                          saveRoutePoint
                        }
                      >
                        {t.savePoint}
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <button
                onClick={() =>
                  setIsMapOpen(false)
                }
                style={{
                  position: 'absolute',
                  top: 24,
                  right: 24,
                  width: 50,
                  height: 50,
                  border: 'none',
                  borderRadius: '50%',
                  cursor: 'pointer',
                  fontSize: 28,
                  background: 'white',
                  color: '#173b70',
                }}
              >
                ×
              </button>
            </div>
          )}
      </div>
    </div>
  );
};

export default AdminMapScreen;