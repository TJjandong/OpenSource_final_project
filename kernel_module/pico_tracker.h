#ifndef PICO_TRACKER_H
#define PICO_TRACKER_H

#include <linux/ioctl.h>

/*
 * Magic Number：識別此裝置的 ioctl 命令空間，使用 ASCII 'p'
 * 避免與其他驅動的 ioctl 命令衝突（參考 Documentation/userspace-api/ioctl/ioctl-number.rst）
 */
#define PICO_TRACKER_IOC_MAGIC 'p'

/*
 * PICO_GET_RSSI — 讀取最新 RSSI 值
 *
 * 使用方式（User Space C）：
 *   int fd = open("/dev/pico_tracker", O_RDWR);
 *   int rssi;
 *   ioctl(fd, PICO_GET_RSSI, &rssi);
 *
 * 使用方式（Python）：
 *   import fcntl, struct
 *   buf = bytearray(4)
 *   fcntl.ioctl(fd, PICO_GET_RSSI, buf)
 *   rssi = struct.unpack('i', buf)[0]
 *
 * 回傳值範圍：
 *   -120 ~ -1 dBm  正常 BLE RSSI
 *   DISCONNECT_SENTINEL (-9999)  Pico 斷線或超時
 *
 * ioctl 方向：_IOR = kernel → userspace（Read from driver）
 */
#define PICO_GET_RSSI _IOR(PICO_TRACKER_IOC_MAGIC, 1, int)

/*
 * DISCONNECT_SENTINEL — 斷線哨兵值
 *
 * 當 BLE kthread 超過 disconnect_timeout_sec 秒未收到目標廣播時，
 * 會將此值推入環形緩衝區。
 *
 * User Space（IoctlSignalSource）收到此值後應顯示斷線警告。
 * 值設為 -9999，遠超出 BLE RSSI 合法範圍（-120 ~ -1 dBm）。
 */
#define DISCONNECT_SENTINEL (-9999)

#endif /* PICO_TRACKER_H */
