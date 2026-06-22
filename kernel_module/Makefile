# Makefile for pico_tracker Linux Kernel Module
#
# 需要 kernel headers 與 Bluetooth subsystem headers：
#   sudo apt install linux-headers-$(uname -r) libbluetooth-dev
#
# 編譯：make
# 清除：make clean
# 載入：sudo insmod pico_tracker.ko [target_name="PicoTracker"] [hci_dev_id=0]
# 卸載：sudo rmmod pico_tracker

obj-m += pico_tracker.o

# 可選：額外的 CFLAGS，-DDEBUG 可啟用詳細 debug printk
# ccflags-y += -DDEBUG

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

# 方便的一鍵載入目標（需要 sudo）
load:
	sudo insmod pico_tracker.ko
	@echo "Module loaded. Check: dmesg | tail -20"

unload:
	sudo rmmod pico_tracker
	@echo "Module unloaded."
