#ifndef PICO_TRACKER_H
#define PICO_TRACKER_H

#include <linux/ioctl.h>

/* 定義 ioctl 命令的 Magic Number */
#define PICO_TRACKER_IOC_MAGIC 'p'

/* 
 * 定義 PICO_GET_RSSI 命令
 * 透過此命令，使用者空間可以獲取最新的 RSSI 數值。
 * 參數: 指向 int 的指標，用於存放讀取到的 RSSI (-128 到 127)
 */
#define PICO_GET_RSSI _IOR(PICO_TRACKER_IOC_MAGIC, 1, int)

#endif /* PICO_TRACKER_H */
