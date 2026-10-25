import OutageMap from "../components/OutageMap.jsx";

/** AEP operations map: the shared outage map plus device pins, hospitals / fire / EMS and % by circuit. */
export default function OpsMap() {
  return <OutageMap aep />;
}
