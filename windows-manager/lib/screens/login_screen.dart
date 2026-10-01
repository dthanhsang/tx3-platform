/// TX3 Manager - Login Screen
import 'package:fluent_ui/fluent_ui.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _serverController = TextEditingController(text: 'http://localhost:8400');
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _licenseController = TextEditingController();
  bool _showPassword = false;
  bool _rememberMe = true;

  @override
  void dispose() {
    _serverController.dispose();
    _usernameController.dispose();
    _passwordController.dispose();
    _licenseController.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    final auth = context.read<AuthProvider>();
    await auth.login(
      _serverController.text.trim(),
      _usernameController.text.trim(),
      _passwordController.text,
      licenseKey: _licenseController.text.trim().isEmpty ? null : _licenseController.text.trim(),
    );
  }

  @override
  Widget build(BuildContext context) {
    return NavigationView(
      content: Center(
        child: SizedBox(
          width: 420,
          child: Card(
            padding: const EdgeInsets.all(32),
            child: Consumer<AuthProvider>(
              builder: (context, auth, _) {
                return Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Logo / Title
                    const Icon(FluentIcons.remote_application, size: 48, color: Color(0xFF0078D4)),
                    const SizedBox(height: 16),
                    Text(
                      'TX3 Manager',
                      style: FluentTheme.of(context).typography.title,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Remote Management Platform',
                      style: FluentTheme.of(context).typography.body?.copyWith(
                            color: const Color(0xFF666666),
                          ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 32),

                    // Server URL
                    InfoLabel(
                      label: 'Management Server',
                      child: TextBox(
                        controller: _serverController,
                        placeholder: 'http://server:8400',
                        prefix: const Padding(
                          padding: EdgeInsets.only(left: 8),
                          child: Icon(FluentIcons.server, size: 16),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // License Key (optional)
                    InfoLabel(
                      label: 'License Key (tùy chọn)',
                      child: TextBox(
                        controller: _licenseController,
                        placeholder: 'TX3-XXXX-XXXX-XXXX',
                        prefix: const Padding(
                          padding: EdgeInsets.only(left: 8),
                          child: Icon(FluentIcons.certificate, size: 16),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Username
                    InfoLabel(
                      label: 'Tài khoản',
                      child: TextBox(
                        controller: _usernameController,
                        placeholder: 'Username',
                        prefix: const Padding(
                          padding: EdgeInsets.only(left: 8),
                          child: Icon(FluentIcons.contact, size: 16),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Password
                    InfoLabel(
                      label: 'Mật khẩu',
                      child: TextBox(
                        controller: _passwordController,
                        placeholder: 'Password',
                        obscureText: !_showPassword,
                        prefix: const Padding(
                          padding: EdgeInsets.only(left: 8),
                          child: Icon(FluentIcons.lock, size: 16),
                        ),
                        suffix: IconButton(
                          icon: Icon(_showPassword ? FluentIcons.hide3 : FluentIcons.view, size: 16),
                          onPressed: () => setState(() => _showPassword = !_showPassword),
                        ),
                        onSubmitted: (_) => _login(),
                      ),
                    ),
                    const SizedBox(height: 12),

                    // Remember me
                    Checkbox(
                      checked: _rememberMe,
                      onChanged: (v) => setState(() => _rememberMe = v ?? true),
                      content: const Text('Ghi nhớ đăng nhập'),
                    ),
                    const SizedBox(height: 20),

                    // Error
                    if (auth.error != null)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: InfoBar(
                          title: const Text('Lỗi'),
                          content: Text(auth.error!),
                          severity: InfoBarSeverity.error,
                        ),
                      ),

                    // License status
                    if (auth.licenseStatus.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: InfoBar(
                          title: const Text('License'),
                          content: Text(auth.licenseStatus),
                          severity: InfoBarSeverity.success,
                        ),
                      ),

                    // Login button
                    FilledButton(
                      onPressed: auth.loading ? null : _login,
                      child: auth.loading
                          ? const SizedBox(
                              height: 16,
                              width: 16,
                              child: ProgressRing(strokeWidth: 2),
                            )
                          : const Text('Đăng nhập'),
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}
