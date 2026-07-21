import { apiRequest } from "./api";

// POST /api/navigation/route
// body: { map_id, start_point_id, end_point_id }
// response: { map_id, start_point_id, end_point_id, path_point_ids,
//              path_details, total_distance }
export function calculateRoute({ mapId, startPointId, endPointId }) {
  return apiRequest("/api/navigation/route", {
    method: "POST",
    body: JSON.stringify({
      map_id: mapId,
      start_point_id: startPointId,
      end_point_id: endPointId,
    }),
  });
}
