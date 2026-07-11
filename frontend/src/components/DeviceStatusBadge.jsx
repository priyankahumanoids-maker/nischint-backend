import { Badge } from "./ui/badge"

export default function DeviceStatusBadge({ status }) {
  if (status === "online") {
    return <Badge data-testid="device-status-online" className="bg-green-500 text-white hover:bg-green-600">Online</Badge>
  }

  if (status === "offline") {
    return <Badge data-testid="device-status-offline" className="bg-red-500 text-white hover:bg-red-600">Offline</Badge>
  }

  return <Badge data-testid="device-status-never-seen" className="bg-gray-400 text-white hover:bg-gray-500">Never Seen</Badge>
}
