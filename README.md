# TX3 Remote Management Platform

Hệ thống quản trị từ xa cho Android TV Box TX3 (Amlogic S905W, 2GB RAM).

## Kiến trúc

```
                     MANAGEMENT SERVER
             +-----------------------------+
             | REST/WebSocket API          |
             | Authentication + License    |
             | Device Provisioning         |
             | PostgreSQL                  |
             +-------------+---------------+
                           |
                     WireGuard Hub
                      10.88.0.1
                           |
          +----------------+----------------+
          |                |                |
      BOX-0001         BOX-0002         BOX-0003
      10.88.0.2        10.88.0.3        10.88.0.4

                  Windows Administrator
                           |
                  TX3 Manager (Flutter)
```

## Thành phần

| Thư mục | Mô tả | Stack |
|---|---|---|
| `management-server/` | API server + database | Python FastAPI + PostgreSQL |
| `android-agent/` | Agent chạy trên Android Box | Shell scripts + native binaries |
| `windows-manager/` | TX3 Manager desktop app | Flutter (Windows) |
| `rom-builder/` | Module tích hợp vào ROM Builder | Python |
| `protocol/` | Protocol definitions chung | JSON/Protobuf |

## Phiên bản

- Platform: 1.0.0
- ROM Builder: v1.0.1
- Agent: 1.0.0
- Protocol: 1
