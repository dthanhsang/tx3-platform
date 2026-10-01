/// TX3 Manager - Main Screen (Navigation Shell)
import 'package:fluent_ui/fluent_ui.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../providers/device_provider.dart';
import 'device_list_screen.dart';
import 'device_detail_screen.dart';

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  int _selectedIndex = 0;

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final devices = context.watch<DeviceProvider>();

    return NavigationView(
      appBar: NavigationAppBar(
        title: const Text('TX3 Manager'),
        actions: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Online/Offline count
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Row(
                children: [
                  Container(
                    width: 8, height: 8,
                    decoration: const BoxDecoration(color: Color(0xFF00C853), shape: BoxShape.circle),
                  ),
                  const SizedBox(width: 4),
                  Text('${devices.onlineCount}', style: const TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(width: 12),
                  Container(
                    width: 8, height: 8,
                    decoration: const BoxDecoration(color: Color(0xFFBDBDBD), shape: BoxShape.circle),
                  ),
                  const SizedBox(width: 4),
                  Text('${devices.offlineCount}'),
                ],
              ),
            ),
            const SizedBox(width: 16),
            // User info
            Text(auth.user?.displayName ?? auth.user?.username ?? ''),
            const SizedBox(width: 8),
            IconButton(
              icon: const Icon(FluentIcons.sign_out, size: 16),
              onPressed: () async {
                final result = await showDialog<bool>(
                  context: context,
                  builder: (ctx) => ContentDialog(
                    title: const Text('Đăng xuất'),
                    content: const Text('Bạn muốn đăng xuất khỏi TX3 Manager?'),
                    actions: [
                      Button(child: const Text('Hủy'), onPressed: () => Navigator.pop(ctx, false)),
                      FilledButton(child: const Text('Đăng xuất'), onPressed: () => Navigator.pop(ctx, true)),
                    ],
                  ),
                );
                if (result == true && context.mounted) {
                  context.read<AuthProvider>().logout();
                }
              },
            ),
            const SizedBox(width: 8),
          ],
        ),
      ),
      pane: NavigationPane(
        selected: _selectedIndex,
        onChanged: (i) => setState(() => _selectedIndex = i),
        displayMode: PaneDisplayMode.compact,
        items: [
          PaneItem(
            icon: const Icon(FluentIcons.devices4),
            title: const Text('Thiết bị'),
            body: devices.selectedDevice != null
                ? DeviceDetailScreen(device: devices.selectedDevice!)
                : const DeviceListScreen(),
          ),
          PaneItem(
            icon: const Icon(FluentIcons.task_list),
            title: const Text('Batch'),
            body: const _BatchScreen(),
          ),
          PaneItem(
            icon: const Icon(FluentIcons.event_info),
            title: const Text('Audit Log'),
            body: const _AuditScreen(),
          ),
        ],
        footerItems: [
          PaneItem(
            icon: const Icon(FluentIcons.settings),
            title: const Text('Cài đặt'),
            body: const _SettingsScreen(),
          ),
        ],
      ),
    );
  }
}

// ── Placeholder screens ──
class _BatchScreen extends StatelessWidget {
  const _BatchScreen();

  @override
  Widget build(BuildContext context) {
    final devices = context.watch<DeviceProvider>();
    return ScaffoldPage.withPadding(
      header: PageHeader(
        title: const Text('Batch Operations'),
        commandBar: CommandBar(
          primaryItems: [
            CommandBarButton(
              icon: const Icon(FluentIcons.installation),
              label: const Text('Install APK'),
              onPressed: () => _showBatchDialog(context, 'install_apk'),
            ),
            CommandBarButton(
              icon: const Icon(FluentIcons.send),
              label: const Text('Send File'),
              onPressed: () => _showBatchDialog(context, 'send_file'),
            ),
            CommandBarButton(
              icon: const Icon(FluentIcons.command_prompt),
              label: const Text('ADB Command'),
              onPressed: () => _showBatchDialog(context, 'adb_command'),
            ),
            CommandBarButton(
              icon: const Icon(FluentIcons.refresh),
              label: const Text('Reboot'),
              onPressed: () => _showBatchDialog(context, 'reboot'),
            ),
          ],
        ),
      ),
      content: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(FluentIcons.task_list, size: 64, color: Color(0xFF999999)),
            const SizedBox(height: 16),
            Text(
              'Chọn thiết bị và thao tác từ thanh công cụ',
              style: FluentTheme.of(context).typography.body,
            ),
            const SizedBox(height: 8),
            Text(
              '${devices.onlineCount} thiết bị online',
              style: FluentTheme.of(context).typography.caption,
            ),
          ],
        ),
      ),
    );
  }

  void _showBatchDialog(BuildContext context, String operation) {
    showDialog(
      context: context,
      builder: (ctx) => ContentDialog(
        title: Text('Batch: $operation'),
        content: const Text('Chọn thiết bị mục tiêu từ danh sách để thực hiện thao tác hàng loạt.'),
        actions: [
          Button(child: const Text('Đóng'), onPressed: () => Navigator.pop(ctx)),
        ],
      ),
    );
  }
}

class _AuditScreen extends StatelessWidget {
  const _AuditScreen();

  @override
  Widget build(BuildContext context) {
    return ScaffoldPage.withPadding(
      header: const PageHeader(title: Text('Audit Log')),
      content: const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(FluentIcons.event_info, size: 64, color: Color(0xFF999999)),
            SizedBox(height: 16),
            Text('Nhật ký hoạt động sẽ hiển thị ở đây.'),
          ],
        ),
      ),
    );
  }
}

class _SettingsScreen extends StatelessWidget {
  const _SettingsScreen();

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    return ScaffoldPage.withPadding(
      header: const PageHeader(title: Text('Cài đặt')),
      content: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Tài khoản', style: FluentTheme.of(context).typography.subtitle),
                const SizedBox(height: 8),
                Text('Username: ${auth.user?.username ?? "—"}'),
                Text('Email: ${auth.user?.email ?? "—"}'),
                Text('Roles: ${auth.user?.roles.join(", ") ?? "—"}'),
                if (auth.licenseStatus.isNotEmpty) Text('License: ${auth.licenseStatus}'),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Server', style: FluentTheme.of(context).typography.subtitle),
                const SizedBox(height: 8),
                Text('URL: ${auth.serverUrl}'),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Phiên bản', style: FluentTheme.of(context).typography.subtitle),
                const SizedBox(height: 8),
                const Text('TX3 Manager v1.0.0'),
                const Text('Protocol v1'),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
