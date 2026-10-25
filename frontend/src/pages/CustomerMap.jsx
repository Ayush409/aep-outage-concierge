import OutageMap from "../components/OutageMap.jsx";

/** Customer map: the shared outage map without AEP-only layers (devices, facilities, circuits). */
export default function CustomerMap() {
  return <OutageMap />;
}
