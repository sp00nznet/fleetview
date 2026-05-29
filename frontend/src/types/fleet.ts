// Fleet data model — TypeScript interfaces matching the FleetView `Fleet` snapshot.
//
// These mirror schema/fleet.schema.json (exported from the pydantic models in
// fleetview/models/*.py). They are intentionally faithful to that contract:
// field names, enum values and nesting all match the exported schema and the
// real public/sample-fleet.json. Optional fields are marked optional/nullable
// the same way the schema's `anyOf [..., null]` shapes them.

export type ProviderKind = 'vmware' | 'proxmox' | 'aws' | 'gcp' | 'unknown';

export type NodeKind = 'vm' | 'container' | 'baremetal' | 'managed' | 'unknown';

export type PowerState = 'running' | 'stopped' | 'suspended' | 'unknown';

export type OSFamily = 'linux' | 'windows' | 'bsd' | 'other' | 'unknown';

export type DiskType = 'ssd' | 'hdd' | 'nvme' | 'network' | 'unknown';

export type FlowMechanism =
  | 'nfs_mount'
  | 'smb_share'
  | 'iscsi'
  | 'rsync'
  | 'scp_cron'
  | 's3_sync'
  | 'tcp_dependency'
  | 'db_connection'
  | 'message_queue'
  | 'http_api'
  | 'shared_volume'
  | 'unknown';

export type FindingSeverity = 'info' | 'low' | 'medium' | 'high' | 'critical';

export type FindingCategory =
  | 'rightsizing'
  | 'cost'
  | 'security'
  | 'reliability'
  | 'modernization'
  | 'hygiene'
  | 'unknown';

export type ConfidenceLevel = 'observed' | 'inferred' | 'assumed';

export interface Placement {
  provider: ProviderKind;
  host?: string | null;
  cluster?: string | null;
  resource_pool?: string | null;
  datacenter?: string | null;
  region?: string | null;
  zone?: string | null;
  folder?: string | null;
}

export interface Compute {
  vcpus?: number | null;
  cores_per_socket?: number | null;
  sockets?: number | null;
  memory_mb?: number | null;
  cpu_model?: string | null;
  architecture?: string | null;
  firmware?: string | null;
  instance_type?: string | null;
}

export interface Disk {
  label?: string | null;
  size_gb?: number | null;
  disk_type: DiskType;
  backing?: string | null;
  path?: string | null;
  provisioning?: string | null;
  encrypted?: boolean | null;
  iops?: number | null;
}

export interface Nic {
  label?: string | null;
  mac?: string | null;
  ips: string[];
  vlan?: number | null;
  network?: string | null;
  switch?: string | null;
  security_groups: string[];
  connected?: boolean | null;
}

export interface OSInfo {
  family: OSFamily;
  distro?: string | null;
  version?: string | null;
  kernel?: string | null;
  hostname?: string | null;
  end_of_life?: boolean | null;
}

export interface Package {
  name: string;
  version?: string | null;
  manager?: string | null;
}

export interface Service {
  name: string;
  state?: string | null;
  description?: string | null;
  exec_path?: string | null;
}

export interface Process {
  pid?: number | null;
  name?: string | null;
  cmdline?: string | null;
  user?: string | null;
}

export interface ListeningPort {
  port: number;
  protocol: string;
  address?: string | null;
  process?: string | null;
}

export interface ContainerInfo {
  id?: string | null;
  name?: string | null;
  image?: string | null;
  image_digest?: string | null;
  runtime?: string | null;
  ports: ListeningPort[];
  state?: string | null;
}

export interface ConfigFile {
  path: string;
  owner?: string | null;
  group?: string | null;
  mode?: string | null;
  size_bytes?: number | null;
  sha256?: string | null;
  belongs_to?: string | null;
  content?: string | null;
}

export interface AppFingerprint {
  name: string;
  category?: string | null;
  version?: string | null;
  confidence: ConfidenceLevel;
  evidence: string[];
}

export interface SoftwareInventory {
  packages: Package[];
  services: Service[];
  processes: Process[];
  listeners: ListeningPort[];
  containers: ContainerInfo[];
  config_files: ConfigFile[];
  fingerprints: AppFingerprint[];
  deep_inspected: boolean;
}

export interface Endpoint {
  node_id?: string | null;
  address?: string | null;
  port?: number | null;
  label?: string | null;
}

export interface DataFlow {
  mechanism: FlowMechanism;
  direction: string; // outbound | inbound | bidirectional
  peer: Endpoint;
  detail?: string | null;
  schedule?: string | null;
  confidence: ConfidenceLevel;
  evidence: string[];
}

export interface Finding {
  id: string;
  category: FindingCategory;
  severity: FindingSeverity;
  title: string;
  detail?: string | null;
  recommendation?: string | null;
  estimated_monthly_savings_usd?: number | null;
  evidence: string[];
}

export interface CostEstimate {
  platform: ProviderKind;
  instance_type?: string | null;
  monthly_usd?: number | null;
  basis?: string | null;
  assumptions: string[];
  is_current: boolean;
}

export interface NodeAnalysis {
  findings: Finding[];
  cost_estimates: CostEstimate[];
}

export interface SourceRef {
  provider: ProviderKind;
  provider_instance?: string | null;
  native_id?: string | null;
  native_type?: string | null;
  raw: Record<string, unknown>;
}

export interface Node {
  id: string;
  name: string;
  kind: NodeKind;
  power_state: PowerState;
  placement: Placement;
  compute: Compute;
  disks: Disk[];
  nics: Nic[];
  os: OSInfo;
  software: SoftwareInventory;
  flows: DataFlow[];
  tags: Record<string, string>;
  annotations?: string | null;
  source: SourceRef;
  analysis?: NodeAnalysis | null;
}

export interface Provider {
  kind: ProviderKind;
  instance: string;
  display_name?: string | null;
  endpoint?: string | null;
  collected_at: string;
  node_count: number;
  extra: Record<string, unknown>;
}

export interface FleetMeta {
  id: string;
  captured_at: string;
  fleetview_version: string;
  scope?: string | null;
  warnings: string[];
}

export interface Fleet {
  meta: FleetMeta;
  providers: Provider[];
  nodes: Node[];
}
