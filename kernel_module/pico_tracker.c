#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/spinlock.h>
#include <linux/timer.h>
#include <linux/jiffies.h>
#include <linux/random.h>
#include "pico_tracker.h"

#define DEVICE_NAME "pico_tracker"
#define BUFFER_SIZE 64

MODULE_LICENSE("GPL");
MODULE_AUTHOR("OpenSource Final Project Team");
MODULE_DESCRIPTION("LKM for Pico Indoor Positioning Tracking System");

static int major_num;
static int device_open_count = 0;

/* 環形緩衝區與自旋鎖 */
static int rssi_buffer[BUFFER_SIZE];
static int head = 0;
static int tail = 0;
static DEFINE_SPINLOCK(buffer_lock);

/* 核心計時器，用於模擬收到藍牙封包 */
static struct timer_list sim_timer;
static int sim_rssi = -60;

/* 將 RSSI 寫入環形緩衝區 */
static void push_rssi(int rssi)
{
    unsigned long flags;
    spin_lock_irqsave(&buffer_lock, flags);
    
    rssi_buffer[head] = rssi;
    head = (head + 1) % BUFFER_SIZE;
    
    /* 如果滿了，覆蓋最舊的資料 */
    if (head == tail) {
        tail = (tail + 1) % BUFFER_SIZE;
    }
    
    spin_unlock_irqrestore(&buffer_lock, flags);
}

/* 從環形緩衝區讀取最新一筆 RSSI，並清空 buffer */
static int pop_latest_rssi(int *rssi)
{
    unsigned long flags;
    int ret = 0;

    spin_lock_irqsave(&buffer_lock, flags);
    
    if (head == tail) {
        /* Buffer is empty: Pico 斷線或尚未收到資料 */
        ret = -1;
    } else {
        /* 取出最新的一筆資料 (head 的前一筆)，不消耗 buffer */
        int latest_idx = (head - 1 + BUFFER_SIZE) % BUFFER_SIZE;
        *rssi = rssi_buffer[latest_idx];
        /* 不移動 tail：讓 GUI 每次都能讀到最後一個寫入的值（含哨兵）。
         * 斷線偵測由 User Space BLE thread 寫入特殊哨兵值 (-9999) 來實現。 */
    }

    spin_unlock_irqrestore(&buffer_lock, flags);
    return ret;
}


/* 模擬收到藍牙封包的 Timer Callback */
static void sim_timer_callback(struct timer_list *timer)
{
    unsigned int rand_val;
    int noise;

    /* 產生模擬的 RSSI 波動 */
    get_random_bytes(&rand_val, sizeof(rand_val));
    noise = (rand_val % 7) - 3; /* -3 to +3 */
    
    sim_rssi += noise;
    if (sim_rssi > -40) sim_rssi = -40;
    if (sim_rssi < -90) sim_rssi = -90;

    push_rssi(sim_rssi);

    /* 重新設定 Timer (約 100ms 一次) */
    mod_timer(&sim_timer, jiffies + msecs_to_jiffies(100));
}


static int dev_open(struct inode *inodep, struct file *filep)
{
    // 移除 device_open_count 限制，允許多重開啟 (讀與寫併發)
    device_open_count++;
    return 0;
}

static int dev_release(struct inode *inodep, struct file *filep)
{
    device_open_count--;
    return 0;
}

/* 提供 write 介面，允許 User Space 或其他驅動將真實 RSSI 寫入 */
static ssize_t dev_write(struct file *filep, const char __user *buffer, size_t len, loff_t *offset)
{
    int rssi_val;
    if (len < sizeof(int)) return -EINVAL;
    
    if (copy_from_user(&rssi_val, buffer, sizeof(int))) {
        return -EFAULT;
    }
    
    push_rssi(rssi_val);
    return sizeof(int);
}

/* ioctl 介面 */
static long dev_ioctl(struct file *filep, unsigned int cmd, unsigned long arg)
{
    int latest_rssi = 0;
    
    switch(cmd) {
        case PICO_GET_RSSI:
            if (pop_latest_rssi(&latest_rssi) == -1) {
                /* 緩衝區沒有資料時，回傳錯誤代碼或是一個特定值 */
                return -ENODATA;
            }
            if (copy_to_user((int __user *)arg, &latest_rssi, sizeof(latest_rssi))) {
                return -EFAULT;
            }
            break;
        default:
            return -ENOTTY;
    }
    
    return 0;
}

static struct file_operations fops = {
    .open = dev_open,
    .release = dev_release,
    .write = dev_write,
    .unlocked_ioctl = dev_ioctl,
};

static int __init pico_tracker_init(void)
{
    major_num = register_chrdev(0, DEVICE_NAME, &fops);
    if (major_num < 0) {
        printk(KERN_ALERT "PicoTracker: Failed to register character device\n");
        return major_num;
    }
    
    printk(KERN_INFO "PicoTracker: Registered correctly with major number %d\n", major_num);
    printk(KERN_INFO "PicoTracker: Please create a device file with: mknod /dev/%s c %d 0\n", DEVICE_NAME, major_num);
    printk(KERN_INFO "PicoTracker: Loaded v2 (with sim_timer)\n");

    /* 啟動模擬用的 Timer (已註解，確保只接收真實藍牙資料) */
    // timer_setup(&sim_timer, sim_timer_callback, 0);
    // mod_timer(&sim_timer, jiffies + msecs_to_jiffies(100));

    return 0;
}

static void __exit pico_tracker_exit(void)
{
    timer_delete_sync(&sim_timer);
    unregister_chrdev(major_num, DEVICE_NAME);
    printk(KERN_INFO "PicoTracker: Unregistered the device\n");
}

module_init(pico_tracker_init);
module_exit(pico_tracker_exit);
