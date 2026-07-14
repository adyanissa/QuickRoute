import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { useAdmin } from '../context/AdminContext';
import '../styles/adminScreens.css';

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
    loadingMaps: 'Loading maps...',
    loadingPoints: 'Loading route points...',
    mapsError: 'Failed to load maps',
    pointsError: 'Failed to load route points',
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
    loadingMaps: 'جاري تحميل الخرائط...',
    loadingPoints: 'جاري تحميل نقاط المسار...',
    mapsError: 'فشل تحميل الخرائط',
    pointsError: 'فشل تحميل نقاط المسار',
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
    loadingMaps: 'טוען מפות...',
    loadingPoints: 'טוען נקודות מסלול...',
    mapsError: 'טעינת המפות נכשלה',
    pointsError: 'טעינת נקודות המסלול נכשלה',
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

const buildAssetUrl = (apiBaseUrl, value) => {
  if (!value) return null;

  if (/^https?:\/\//i.test(value) || value.startsWith('data:')) {
    return value;
  }

  const cleanBase = String(apiBaseUrl || '').replace(/\/$/, '');
  const cleanPath = value.startsWith('/') ? value : `/${value}`;

  return `${cleanBase}${cleanPath}`;
};

const normalizeMap = (map, apiBaseUrl) => {
  if (!map) return null;

  const imageUrl = buildAssetUrl(
    apiBaseUrl,
    map.image_url ?? map.imageUrl,
  );

  const sourceImageUrl = buildAssetUrl(
    apiBaseUrl,
    map.source_image_url ?? map.sourceImageUrl,
  );

  const displayImageUrl = buildAssetUrl(
    apiBaseUrl,
    map.display_image_url ?? map.displayImageUrl,
  );

  return {
    ...map,
    id: map.id ?? map._id,
    imageUrl,
    sourceImageUrl,
    displayImageUrl,
    hasImage: Boolean(
      imageUrl ||
        sourceImageUrl ||
        displayImageUrl,
    ),
    isCurrent: Boolean(
      map.is_current ??
        map.isCurrent,
    ),
    processingStatus:
      map.processing_status ??
      map.processingStatus ??
      'not_started',
    processingProgress: Number(
      map.processing_progress ??
        map.processingProgress ??
        0,
    ),
    processingError:
      map.processing_error ??
      map.processingError ??
      null,
  };
};

const AdminMapScreen = () => {
  const { lang, setLang } = useLang();
  const { API_BASE_URL } = useAdmin();
  const navigate = useNavigate();

  const apiBaseUrl =
    API_BASE_URL ||
    'http://127.0.0.1:8000';

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
        const response = await fetch(
          `${apiBaseUrl}/api/maps`,
        );

        if (!response.ok) {
          throw new Error(await response.text());
        }

        const data = await response.json();

        const normalizedMaps = Array.isArray(data)
          ? data.map((map) =>
              normalizeMap(map, apiBaseUrl),
            )
          : [];

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
    [apiBaseUrl, t.mapsError],
  );

  useEffect(() => {
    loadMaps();
  }, [loadMaps]);

  useEffect(() => {
    let cancelled = false;

    const loadRoutePoints = async () => {
      setClickedPoint(null);
      setPointsError('');

      if (!selectedMapId) {
        setRoutePoints([]);
        return;
      }

      setIsPointsLoading(true);

      try {
        const response = await fetch(
          `${apiBaseUrl}/api/route-points?map_id=${encodeURIComponent(
            selectedMapId,
          )}`,
        );

        if (!response.ok) {
          throw new Error(await response.text());
        }

        const data = await response.json();

        if (!cancelled) {
          setRoutePoints(
            Array.isArray(data) ? data : [],
          );
        }
      } catch (error) {
        console.error(
          'Failed to load route points:',
          error,
        );

        if (!cancelled) {
          setRoutePoints([]);
          setPointsError(t.pointsError);
        }
      } finally {
        if (!cancelled) {
          setIsPointsLoading(false);
        }
      }
    };

    loadRoutePoints();

    return () => {
      cancelled = true;
    };
  }, [
    apiBaseUrl,
    selectedMapId,
    t.pointsError,
  ]);

  useEffect(() => {
    if (!pollingMapId) return undefined;

    let cancelled = false;
    let timerId;

    const checkStatus = async () => {
      try {
        const response = await fetch(
          `${apiBaseUrl}/api/maps/${pollingMapId}/processing-status`,
        );

        if (!response.ok) {
          throw new Error(await response.text());
        }

        const statusData = await response.json();

        if (cancelled) return;

        setMaps((previousMaps) =>
          previousMaps.map((map) =>
            map.id === pollingMapId
              ? normalizeMap(
                  {
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
                  },
                  apiBaseUrl,
                )
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
    apiBaseUrl,
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
      const response = await fetch(
        `${apiBaseUrl}/api/maps/${mapId}`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            is_current: true,
          }),
        },
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const selectedMap = normalizeMap(
        await response.json(),
        apiBaseUrl,
      );

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
      const response = await fetch(
        `${apiBaseUrl}/api/maps/${activeMap.id}`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const updatedMap = normalizeMap(
        await response.json(),
        apiBaseUrl,
      );

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
      const response = await fetch(
        `${apiBaseUrl}/api/maps/${activeMap.id}`,
        {
          method: 'DELETE',
        },
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      setRoutePoints([]);
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
      const response = await fetch(
        `${apiBaseUrl}/api/maps/upload`,
        {
          method: 'POST',
          body: formData,
        },
      );

      if (!response.ok) {
        let message = await response.text();

        try {
          const parsed = JSON.parse(message);

          message =
            parsed.detail ||
            message;
        } catch {
          // Keep backend text.
        }

        throw new Error(message);
      }

      const newMap = normalizeMap(
        await response.json(),
        apiBaseUrl,
      );

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

    setClickedPoint({ x, y });
    setPointName(`Point ${x},${y}`);
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
      building_id: null,
      room_id: null,
      is_accessible: true,
    };

    try {
      const response = await fetch(
        `${apiBaseUrl}/api/route-points`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const savedPoint = await response
        .json()
        .catch(() => payload);

      setRoutePoints(
        (previousPoints) => [
          ...previousPoints,
          savedPoint,
        ],
      );

      setClickedPoint(null);
      setPointName('');
      setPointType('hallway');
      setFloor(0);

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

  const markerPosition = (point) => {
    if (!fullMapMetrics) return null;

    const pointX = Number(point.x);
    const pointY = Number(point.y);

    if (
      !Number.isFinite(pointX) ||
      !Number.isFinite(pointY)
    ) {
      return null;
    }

    return {
      left:
        (pointX /
          fullMapMetrics.naturalWidth) *
        fullMapMetrics.displayWidth,

      top:
        (pointY /
          fullMapMetrics.naturalHeight) *
        fullMapMetrics.displayHeight,
    };
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

                {routePoints.map(
                  (point) => {
                    const position =
                      markerPosition(point);

                    if (!position) {
                      return null;
                    }

                    return (
                      <div
                        key={
                          point.id ||
                          point._id ||
                          `${point.x}-${point.y}-${point.name}`
                        }
                        title={
                          point.name ||
                          'Route point'
                        }
                        style={{
                          position:
                            'absolute',
                          left:
                            position.left -
                            6,
                          top:
                            position.top -
                            6,
                          width: 12,
                          height: 12,
                          borderRadius:
                            '50%',
                          background:
                            '#28a745',
                          border:
                            '2px solid white',
                          boxShadow:
                            '0 0 7px rgba(0, 0, 0, 0.45)',
                          pointerEvents:
                            'none',
                        }}
                      />
                    );
                  },
                )}

                {clickedPoint &&
                  (() => {
                    const position =
                      markerPosition(
                        clickedPoint,
                      );

                    if (!position) {
                      return null;
                    }

                    return (
                      <div
                        style={{
                          position:
                            'absolute',
                          left:
                            position.left -
                            7,
                          top:
                            position.top -
                            7,
                          width: 14,
                          height: 14,
                          borderRadius:
                            '50%',
                          background: 'red',
                          border:
                            '2px solid white',
                          boxShadow:
                            '0 0 8px rgba(0, 0, 0, 0.5)',
                          pointerEvents:
                            'none',
                        }}
                      />
                    );
                  })()}

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

                {clickedPoint && (
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

                        <option value="stairs">
                          stairs
                        </option>

                        <option value="elevator">
                          elevator
                        </option>

                        <option value="room">
                          room
                        </option>
                      </select>
                    </div>

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

                    <div className="adm-form-actions">
                      <button
                        className="adm-btn adm-btn-cancel"
                        onClick={() => {
                          setClickedPoint(
                            null,
                          );

                          setPointName('');
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