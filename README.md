# QuickRoute

QuickRoute is an indoor navigation project that helps users find the shortest route inside a campus, hospital, or building environment.

The project currently includes:

- React Frontend
- Flask Backend
- REST API endpoints
- Mock JSON data
- Buildings and rooms API
- Graph data with nodes and edges
- Shortest path route calculation using Dijkstra algorithm

---

## Project Structure

```txt
QuickRoute/
│
├── frontend/
│   └── React app
│
├── backend/
│   ├── app.py
│   │
│   ├── data/
│   │   ├── buildings.json
│   │   ├── rooms.json
│   │   └── map_graph.json
│   │
│   ├── routes/
│   │   └── navigation_routes.py
│   │
│   └── services/
│       └── route_service.py
│
└── README.md
```

---

## Backend

The backend is built with Flask.

It reads data from JSON files and exposes REST API endpoints for:

- Buildings
- Rooms
- Graph data
- Shortest route calculation

---

## Backend Requirements

Make sure Python is installed.

Install the required packages:

```bash
pip install flask flask-cors
```

---

## Run Backend

From the project root folder:

```bash
cd backend
python app.py
```

The backend should run on:

```txt
http://127.0.0.1:5000
```

If it works correctly, you should see:

```txt
Running on http://127.0.0.1:5000
```

---

## Backend API Endpoints

### Check if backend is running

```txt
GET http://127.0.0.1:5000/
```

Expected response:

```json
{
  "message": "Backend is running 🚀"
}
```

---

### Get all buildings

```txt
GET http://127.0.0.1:5000/buildings
```

This endpoint returns the list of available buildings.

---

### Get rooms by building

```txt
GET http://127.0.0.1:5000/buildings/heart/rooms
```

This endpoint returns all rooms inside a selected building.

---

### Get room by ID

```txt
GET http://127.0.0.1:5000/rooms/hrt-2
```

This endpoint returns one specific room by its ID.

---

### Get map graph

```txt
GET http://127.0.0.1:5000/graph
```

This endpoint returns the graph data used for navigation.

The graph includes:

- nodes
- edges
- distances

---

### Calculate shortest route

```txt
GET http://127.0.0.1:5000/route?from=main_entrance&to=heart_lab
```

Example response:

```json
{
  "from": "main_entrance",
  "to": "heart_lab",
  "path": [
    "main_entrance",
    "heart_entrance",
    "heart_reception",
    "heart_lab"
  ],
  "totalDistance": 53
}
```

---

## Frontend

The frontend is built with React.

It is used to display:

- The user interface
- Buildings
- Rooms
- Maps
- Route results

---

## Frontend Requirements

Make sure Node.js and npm are installed.

Install frontend dependencies:

```bash
cd frontend
npm install
```

---

## Run Frontend

Open a new terminal.

From the project root folder:

```bash
cd frontend
npm run dev
```

The frontend usually runs on:

```txt
http://localhost:5173
```

---

## Run Full Project

To run the full project, open two terminals.

### Terminal 1: Backend

```bash
cd backend
python app.py
```

### Terminal 2: Frontend

```bash
cd frontend
npm run dev
```

Backend URL:

```txt
http://127.0.0.1:5000
```

Frontend URL:

```txt
http://localhost:5173
```

---

## Current Backend Status

The backend currently supports:

- Flask server
- REST API
- JSON data loading
- Buildings API
- Rooms API
- Graph API
- Shortest path route API
- Dijkstra route calculation
- Organized backend structure using routes and services

---

## Important Notes

The current data is mock data.

The backend currently reads from JSON files:

```txt
backend/data/buildings.json
backend/data/rooms.json
backend/data/map_graph.json
```

In the future, this mock data can be replaced with:

- Real building data
- Real rooms data
- Real map graph data
- Database tables

---

## Next Steps

The next development steps are:

- Connect React frontend with Flask backend
- Fetch buildings from the backend instead of using frontend dummy data
- Display rooms based on the selected building
- Display route results on the map
- Replace mock data with real map data
- Move JSON data into a real database later