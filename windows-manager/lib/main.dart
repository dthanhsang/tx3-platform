import 'package:flutter/material.dart';
import 'package:fluent_ui/fluent_ui.dart' hide Colors;
import 'package:provider/provider.dart';
import 'package:window_manager/window_manager.dart';

import 'providers/auth_provider.dart';
import 'providers/device_provider.dart';
import 'providers/remote_provider.dart';
import 'providers/transfer_provider.dart';
import 'screens/login_screen.dart';
import 'screens/main_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();

  const windowOptions = WindowOptions(
    size: Size(1400, 900),
    minimumSize: Size(1000, 700),
    center: true,
    title: 'TX3 Manager',
    titleBarStyle: TitleBarStyle.normal,
  );

  await windowManager.waitUntilReadyToShow(windowOptions, () async {
    await windowManager.show();
    await windowManager.focus();
  });

  runApp(const TX3ManagerApp());
}

class TX3ManagerApp extends StatelessWidget {
  const TX3ManagerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AuthProvider()),
        ChangeNotifierProxyProvider<AuthProvider, DeviceProvider>(
          create: (_) => DeviceProvider(),
          update: (_, auth, devices) => devices!..updateAuth(auth),
        ),
        ChangeNotifierProvider(create: (_) => RemoteProvider()),
        ChangeNotifierProvider(create: (_) => TransferProvider()),
      ],
      child: FluentApp(
        title: 'TX3 Manager',
        debugShowCheckedModeBanner: false,
        theme: FluentThemeData(
          brightness: Brightness.light,
          accentColor: Colors.blue.toAccentColor(),
          visualDensity: VisualDensity.standard,
        ),
        darkTheme: FluentThemeData(
          brightness: Brightness.dark,
          accentColor: Colors.blue.toAccentColor(),
          visualDensity: VisualDensity.standard,
        ),
        themeMode: ThemeMode.system,
        home: const AuthGate(),
      ),
    );
  }
}

class AuthGate extends StatelessWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<AuthProvider>(
      builder: (context, auth, _) {
        if (auth.isAuthenticated) {
          return const MainScreen();
        }
        return const LoginScreen();
      },
    );
  }
}
