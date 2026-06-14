import { apiRequest } from "./api";

export function getBuildings() {
  return apiRequest("/api/locations/buildings");
}

export function getBuildingById(buildingId) {
  return apiRequest(`/api/locations/buildings/${buildingId}`);
}

export function createBuilding(buildingData) {
  return apiRequest("/api/locations/buildings", {
    method: "POST",
    body: JSON.stringify(buildingData),
  });
}

export function updateBuilding(buildingId, buildingData) {
  return apiRequest(`/api/locations/buildings/${buildingId}`, {
    method: "PUT",
    body: JSON.stringify(buildingData),
  });
}

export function deleteBuilding(buildingId) {
  return apiRequest(`/api/locations/buildings/${buildingId}`, {
    method: "DELETE",
  });
}