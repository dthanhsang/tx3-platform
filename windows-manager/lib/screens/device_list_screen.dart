/// TX3 Manager - Device List Screen
import 'package:fluent_ui/fluent_ui.dart';
import 'package:provider/provider.dart';
import '../models/models.dart';
import '../providers/device_provider.dart';

class DeviceListScreen extends StatefulWidget {
  const DeviceListScreen({super.key});

  @override
  State<DeviceListScreen> createState() => _DeviceListScreenState();
}

class _DeviceListScreenState extends State<DeviceListScreen> {
  final _searchController = TextEditingController();
  String? _statusFilter;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<DeviceProvider>();
    final devices = provider.filteredDevices;

    return ScaffoldPage(
      header: PageHeader(
        title: const Text('Thiết bị'),
        commandBar: CommandBar(
          primaryItems: [
            CommandBarButton(
              icon: const Icon(FluentIcons.refresh),
              label: const Text('Làm mới'),
              onPressed: () => provider.loadDevices(),
            ),
          ],
        ),
      ),
      content: Column(
        children: [
          // ── Search & Filter Bar ──
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                Expanded(
                  child: TextBox(
                    controller: _searchController,
                    placeholder: 'Tìm kiếm thiết bị, vị trí, MAC, IP, ghi chú, tag...',
                    prefix: const Padding(
                      padding: EdgeInsets.only(left: 8),
                      child: Icon(FluentIcons.search, size: 14),
                    ),
                    suffix: _searchController.text.isNotEmpty
                        ? IconButton(
                            icon: const Icon(FluentIcons.clear, size: 12),
                            onPressed: () {
                              _searchController.clear();
                              provider.setSearchQuery('');
                            },
                          )
                        : null,
                    onChanged: (v) => provider.setSearchQuery(v),
                  ),
                ),
                const SizedBox(width: 12),
                ComboBox<String?>(
                  value: _statusFilter,
                  placeholder: const Text('Trạng thái'),
                  items: const [
                    ComboBoxItem(value: null, child: Text('Tất cả')),
                    ComboBoxItem(value: 'online', child: Text('Online')),
                    ComboBoxItem(value: 'offline', child: Text('Offline')),
                    ComboBoxItem(value: 'pending', child: Text('Pending')),
                  ],
                  onChanged: (v) {
                    setState(() => _statusFilter = v);
                    provider.setStatusFilter(v);
                  },
                ),
                const SizedBox(width: 12),
                // Summary
                Text(
                  '${devices.length} thiết bị',
                  style: FluentTheme.of(context).typography.caption,
                ),
              ],
            ),
          ),

          // ── Device Table ──
          Expanded(
            child: provider.loading && devices.isEmpty
                ? const Center(child: ProgressRing())
                : devices.isEmpty
                    ? Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(FluentIcons.devices4, size: 64, color: Color(0xFF999999)),
                            const SizedBox(height: 16),
                            Text(
                              provider.searchQuery.isNotEmpty
                                  ? 'Không tìm thấy thiết bị phù hợp'
                                  : 'Chưa có thiết bị nào',
                              style: FluentTheme.of(context).typography.body,
                            ),
                          ],
                        ),
                      )
                    : ListView.builder(
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        itemCount: devices.length,
                        itemBuilder: (ctx, index) => _DeviceCard(
                          device: devices[index],
                          onTap: () => provider.selectDevice(devices[index].id),
                        ),
                      ),
          ),

          // ── Error Bar ──
          if (provider.error != null)
            Padding(
              padding: const EdgeInsets.all(16),
              child: InfoBar(
                title: const Text('Lỗi'),
                content: Text(provider.error!),
                severity: InfoBarSeverity.error,
              ),
            ),
        ],
      ),
    );
  }
}

class _DeviceCard extends StatelessWidget {
  final Device device;
  final VoidCallback onTap;

  const _DeviceCard({required this.device, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final theme = FluentTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: ListTile.selectable(
        onPressed: onTap,
        leading: Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(
            color: device.isOnline ? const Color(0xFF00C853) : const Color(0xFFBDBDBD),
            shape: BoxShape.circle,
          ),
        ),
        title: Row(
          children: [
            Expanded(
              flex: 2,
              child: Text(
                device.displayName,
                style: theme.typography.body?.copyWith(fontWeight: FontWeight.w600),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            Expanded(
              flex: 3,
              child: Text(
                device.location?.displayLocation ?? '—',
                style: theme.typography.caption,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            SizedBox(
              width: 120,
              child: Text(
                device.wgIp ?? '—',
                style: theme.typography.caption?.copyWith(fontFamily: 'Consolas'),
              ),
            ),
            SizedBox(
              width: 70,
              child: Text(
                device.status.toUpperCase(),
                style: theme.typography.caption?.copyWith(
                  color: device.isOnline ? const Color(0xFF00C853) : const Color(0xFF999999),
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ],
        ),
        subtitle: Row(
          children: [
            if (device.model != null) ...[
              Text(device.model!, style: theme.typography.caption),
              const SizedBox(width: 12),
            ],
            if (device.romVersion != null) ...[
              Text('ROM ${device.romVersion}', style: theme.typography.caption),
              const SizedBox(width: 12),
            ],
            if (device.tags.isNotEmpty)
              ...device.tags.take(3).map(
                    (t) => Padding(
                      padding: const EdgeInsets.only(right: 4),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                        decoration: BoxDecoration(
                          color: theme.accentColor.withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(t, style: theme.typography.caption?.copyWith(fontSize: 10)),
                      ),
                    ),
                  ),
          ],
        ),
      ),
    );
  }
}
