/// TX3 Manager - Device Detail Screen
import 'package:fluent_ui/fluent_ui.dart';
import 'package:provider/provider.dart';
import '../models/models.dart';
import '../providers/device_provider.dart';
import '../providers/remote_provider.dart';

class DeviceDetailScreen extends StatefulWidget {
  final Device device;
  const DeviceDetailScreen({super.key, required this.device});

  @override
  State<DeviceDetailScreen> createState() => _DeviceDetailScreenState();
}

class _DeviceDetailScreenState extends State<DeviceDetailScreen> {
  int _tabIndex = 0;

  @override
  Widget build(BuildContext context) {
    final theme = FluentTheme.of(context);
    final d = widget.device;
    final remote = context.watch<RemoteProvider>();

    return ScaffoldPage(
      header: PageHeader(
        title: Row(
          children: [
            IconButton(
              icon: const Icon(FluentIcons.back),
              onPressed: () => context.read<DeviceProvider>().clearSelection(),
            ),
            const SizedBox(width: 8),
            Container(
              width: 12, height: 12,
              decoration: BoxDecoration(
                color: d.isOnline ? const Color(0xFF00C853) : const Color(0xFFBDBDBD),
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 8),
            Text(d.displayName),
            const SizedBox(width: 12),
            Text(
              d.status.toUpperCase(),
              style: theme.typography.caption?.copyWith(
                color: d.isOnline ? const Color(0xFF00C853) : const Color(0xFF999999),
                fontWeight: FontWeight.bold,
              ),
            ),
          ],
        ),
        commandBar: CommandBar(
          primaryItems: [
            CommandBarButton(
              icon: const Icon(FluentIcons.remote_application),
              label: const Text('REMOTE'),
              onPressed: d.isOnline ? () => _startRemote(context) : null,
            ),
            CommandBarButton(
              icon: const Icon(FluentIcons.fabric_folder),
              label: const Text('FILES'),
              onPressed: d.isOnline ? () => setState(() => _tabIndex = 1) : null,
            ),
            CommandBarButton(
              icon: const Icon(FluentIcons.command_prompt),
              label: const Text('ADB'),
              onPressed: d.isOnline ? () => setState(() => _tabIndex = 2) : null,
            ),
            CommandBarButton(
              icon: const Icon(FluentIcons.installation),
              label: const Text('INSTALL APK'),
              onPressed: d.isOnline ? () => _installApk(context) : null,
            ),
            CommandBarButton(
              icon: const Icon(FluentIcons.refresh),
              label: const Text('REBOOT'),
              onPressed: d.isOnline ? () => _rebootDevice(context) : null,
            ),
          ],
        ),
      ),
      content: Column(
        children: [
          // ── Device Info Cards ──
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                _InfoCard(title: 'Model', value: d.model ?? '—', icon: FluentIcons.devices4),
                const SizedBox(width: 8),
                _InfoCard(title: 'WG IP', value: d.wgIp ?? '—', icon: FluentIcons.server),
                const SizedBox(width: 8),
                _InfoCard(title: 'ROM', value: d.romVersion ?? '—', icon: FluentIcons.system),
                const SizedBox(width: 8),
                _InfoCard(title: 'Uptime', value: d.uptimeDisplay, icon: FluentIcons.timer),
                const SizedBox(width: 8),
                _InfoCard(title: 'RAM', value: d.ramMb != null ? '${d.ramMb} MB' : '—', icon: FluentIcons.processing),
              ],
            ),
          ),

          // ── Tab Content ──
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: TabView(
                currentIndex: _tabIndex,
                onChanged: (i) => setState(() => _tabIndex = i),
                tabs: [
                  Tab(
                    text: const Text('Chi tiết'),
                    body: _DeviceInfoTab(device: d),
                    icon: const Icon(FluentIcons.info, size: 14),
                  ),
                  Tab(
                    text: const Text('Files'),
                    body: _FilesTab(device: d),
                    icon: const Icon(FluentIcons.fabric_folder, size: 14),
                  ),
                  Tab(
                    text: const Text('ADB'),
                    body: _AdbTab(device: d),
                    icon: const Icon(FluentIcons.command_prompt, size: 14),
                  ),
                  if (remote.streaming && remote.activeSessionId != null)
                    Tab(
                      text: const Text('Remote'),
                      body: _RemoteTab(device: d),
                      icon: const Icon(FluentIcons.remote_application, size: 14),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _startRemote(BuildContext context) {
    final remote = context.read<RemoteProvider>();
    remote.startRemote(widget.device.deviceUuid);
    setState(() => _tabIndex = 3); // Switch to remote tab
  }

  Future<void> _rebootDevice(BuildContext context) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => ContentDialog(
        title: const Text('Reboot thiết bị'),
        content: Text('Bạn muốn reboot ${widget.device.displayName}?'),
        actions: [
          Button(child: const Text('Hủy'), onPressed: () => Navigator.pop(ctx, false)),
          FilledButton(
            style: ButtonStyle(backgroundColor: WidgetStateProperty.all(const Color(0xFFD32F2F))),
            child: const Text('Reboot'),
            onPressed: () => Navigator.pop(ctx, true),
          ),
        ],
      ),
    );
    if (result == true && context.mounted) {
      await context.read<DeviceProvider>().rebootDevice(widget.device.id);
    }
  }

  void _installApk(BuildContext context) {
    // TODO: File picker + upload + install flow
    showDialog(
      context: context,
      builder: (ctx) => ContentDialog(
        title: const Text('Cài APK'),
        content: const Text('Chọn file APK để cài đặt lên thiết bị.\n\nFile sẽ được upload qua WireGuard và cài tự động.'),
        actions: [
          Button(child: const Text('Đóng'), onPressed: () => Navigator.pop(ctx)),
        ],
      ),
    );
  }
}

class _InfoCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;

  const _InfoCard({required this.title, required this.value, required this.icon});

  @override
  Widget build(BuildContext context) {
    final theme = FluentTheme.of(context);
    return Expanded(
      child: Card(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 14, color: theme.accentColor),
                const SizedBox(width: 6),
                Text(title, style: theme.typography.caption),
              ],
            ),
            const SizedBox(height: 4),
            Text(value, style: theme.typography.body?.copyWith(fontWeight: FontWeight.w600)),
          ],
        ),
      ),
    );
  }
}

// ── Device Info Tab ──
class _DeviceInfoTab extends StatelessWidget {
  final Device device;
  const _DeviceInfoTab({required this.device});

  @override
  Widget build(BuildContext context) {
    final d = device;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Location
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Vị trí', style: FluentTheme.of(context).typography.subtitle),
                const SizedBox(height: 8),
                _row('Khách hàng', d.location?.customer),
                _row('Site', d.location?.site),
                _row('Tòa', d.location?.building),
                _row('Tầng', d.location?.floor),
                _row('Phòng', d.location?.room),
                _row('Ghi chú', d.location?.note),
              ],
            ),
          ),
          const SizedBox(height: 12),
          // Hardware
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Phần cứng', style: FluentTheme.of(context).typography.subtitle),
                const SizedBox(height: 8),
                _row('Device UUID', d.deviceUuid),
                _row('MAC Wi-Fi', d.macWifi),
                _row('MAC Ethernet', d.macEthernet),
                _row('Serial', d.serial),
                _row('Model', d.model),
                _row('SoC', d.soc),
                _row('RAM', d.ramMb != null ? '${d.ramMb} MB' : null),
              ],
            ),
          ),
          const SizedBox(height: 12),
          // Software
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Phần mềm', style: FluentTheme.of(context).typography.subtitle),
                const SizedBox(height: 8),
                _row('ROM Version', d.romVersion),
                _row('Agent Version', d.agentVersion),
                _row('WireGuard IP', d.wgIp),
                _row('Last Seen', d.lastSeen?.toLocal().toString()),
                _row('Uptime', d.uptimeDisplay),
              ],
            ),
          ),
          const SizedBox(height: 12),
          // Tags
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Tags', style: FluentTheme.of(context).typography.subtitle),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: d.tags
                      .map((t) => Chip(
                            text: Text(t),
                            onPressed: () {},
                          ))
                      .toList(),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _row(String label, String? value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          SizedBox(width: 140, child: Text('$label:', style: const TextStyle(fontWeight: FontWeight.w500))),
          Expanded(child: Text(value ?? '—')),
        ],
      ),
    );
  }
}

// ── Files Tab (placeholder) ──
class _FilesTab extends StatelessWidget {
  final Device device;
  const _FilesTab({required this.device});

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(FluentIcons.fabric_folder, size: 64, color: Color(0xFF999999)),
          SizedBox(height: 16),
          Text('File Browser'),
          SizedBox(height: 8),
          Text('Duyệt, upload, download file từ thiết bị.\nHỗ trợ drag & drop, resume, hash verification.'),
        ],
      ),
    );
  }
}

// ── ADB Tab (placeholder) ──
class _AdbTab extends StatelessWidget {
  final Device device;
  const _AdbTab({required this.device});

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(FluentIcons.command_prompt, size: 64, color: Color(0xFF999999)),
          SizedBox(height: 16),
          Text('Remote ADB Console'),
          SizedBox(height: 8),
          Text('Chạy lệnh ADB từ xa qua WireGuard.\nCollect logs, device info, storage info.'),
        ],
      ),
    );
  }
}

// ── Remote Tab ──
class _RemoteTab extends StatelessWidget {
  final Device device;
  const _RemoteTab({required this.device});

  @override
  Widget build(BuildContext context) {
    final remote = context.watch<RemoteProvider>();
    return Column(
      children: [
        // Toolbar
        Padding(
          padding: const EdgeInsets.all(8),
          child: Row(
            children: [
              // Android keys
              IconButton(icon: const Icon(FluentIcons.back), onPressed: () => remote.sendAndroidKey('back')),
              IconButton(icon: const Icon(FluentIcons.home), onPressed: () => remote.sendAndroidKey('home')),
              IconButton(icon: const Icon(FluentIcons.list), onPressed: () => remote.sendAndroidKey('recent')),
              const SizedBox(width: 16),
              // Volume
              IconButton(icon: const Icon(FluentIcons.volume3), onPressed: () => remote.sendAndroidKey('volume_up')),
              IconButton(icon: const Icon(FluentIcons.volume0), onPressed: () => remote.sendAndroidKey('volume_down')),
              const Spacer(),
              // Stream info
              Text('${remote.width}x${remote.height} @ ${remote.fps}fps ${remote.bitrateKbps}kbps'),
              if (remote.hwEncoder)
                const Padding(
                  padding: EdgeInsets.only(left: 8),
                  child: InfoBadge(source: Text('HW'), color: Color(0xFF00C853)),
                ),
              const SizedBox(width: 16),
              // Stop button
              FilledButton(
                style: ButtonStyle(backgroundColor: WidgetStateProperty.all(const Color(0xFFD32F2F))),
                child: const Text('Ngắt kết nối'),
                onPressed: () => remote.stopRemote(),
              ),
            ],
          ),
        ),
        // Video area (placeholder - actual H.264 decoding would use platform channel)
        Expanded(
          child: Container(
            margin: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: const Color(0xFF1A1A1A),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(FluentIcons.remote_application, size: 64, color: Color(0xFF666666)),
                  const SizedBox(height: 16),
                  Text(
                    remote.streaming ? 'Remote Session Active' : 'Connecting...',
                    style: const TextStyle(color: Color(0xFF999999), fontSize: 18),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'H.264 video stream sẽ hiển thị ở đây.\n'
                    'Mouse click, keyboard, D-Pad đều được forward.',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: Color(0xFF666666)),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}
