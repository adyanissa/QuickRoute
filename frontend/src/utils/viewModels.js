// Shared adapters that translate real backend Building/Room records
// (snake_case) into the simple view-model shape the UI components
// (DestinationCard, admin screens) expect. Kept separate from any one
// screen so BuildingSelectionScreen, DestinationSelectionScreen and the
// admin screens all read the same real data the same way.

export const buildingToViewModel = (b) => ({
  id: b.id,
  nameEn: b.name_en || '',
  name: b.name_local || '',
  subtitle: b.description || '',
  tag: b.short_tag || '',
  category: b.category || 'general',
  iconColor: b.icon_color || '#2a5298',
  iconBg: `${b.icon_color || '#2a5298'}1f`,
});

export const roomToViewModel = (r) => ({
  id: r.id,
  name: r.name_en || '',
  type: r.room_type || 'room',
  floor: r.floor ?? 0,
  description: r.description || '',
  buildingId: r.building_id,
});
