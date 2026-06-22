/*
 * pico_tracker.c — Linux Kernel Module for Pico Indoor Positioning System
 * 版本: V3.7 (Ultimate Final Edition)
 * 包含: User Channel 接管、HCI Reset、Event Mask 解封印、獨立斷線偵測
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/spinlock.h>
#include <linux/kthread.h>
#include <linux/delay.h>
#include <linux/string.h>
#include <linux/slab.h>
#include <linux/socket.h>
#include <linux/version.h>
#include <net/sock.h>
#include "pico_tracker.h"

#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 7, 0)
typedef struct sockaddr_unsized pt_bind_sa_t;
#else
typedef struct sockaddr         pt_bind_sa_t;
#endif

#ifndef AF_BLUETOOTH
#  define AF_BLUETOOTH 31
#endif
#ifndef BTPROTO_HCI
#  define BTPROTO_HCI  1
#endif

#define PT_HCI_CHANNEL_USER 1

struct pt_sockaddr_hci {
    sa_family_t    hci_family;
    unsigned short hci_dev;
    unsigned short hci_channel;
};

#define PT_HCI_CMD_PKT   0x01
#define PT_HCI_EVENT_PKT 0x04

#define PT_HCI_OP_RESET              0x0C03u
#define PT_HCI_OP_SET_EVENT_MASK     0x0C01u
#define PT_HCI_OP_LE_SET_EVENT_MASK  0x2001u
#define PT_HCI_OP_LE_SET_SCAN_PARAM  0x200Bu
#define PT_HCI_OP_LE_SET_SCAN_ENABLE 0x200Cu

#define PT_HCI_EV_LE_META       0x3Eu
#define PT_HCI_EV_LE_ADV_REPORT 0x02u

#define PT_AD_TYPE_SHORT_NAME    0x08u
#define PT_AD_TYPE_COMPLETE_NAME 0x09u

struct pt_le_scan_param_cp {
    __u8   type;
    __le16 interval;
    __le16 window;
    __u8   own_address_type;
    __u8   filter_policy;
} __packed;

struct pt_le_scan_enable_cp {
    __u8 enable;
    __u8 filter_dup;
} __packed;

#define DEVICE_NAME  "pico_tracker"
#define BUFFER_SIZE  64

MODULE_LICENSE("GPL");
MODULE_AUTHOR("OpenSource Final Project Team");
MODULE_DESCRIPTION("Pico Tracker LKM v3.7 (Ultimate Final Edition)");
MODULE_VERSION("3.7");

static char *target_name = "PicoTracker";
module_param(target_name, charp, 0444);
static char *target_mac = "";
module_param(target_mac, charp, 0444);
static int hci_dev_id = 0;
module_param(hci_dev_id, int, 0444);
static int disconnect_timeout_sec = 3;
module_param(disconnect_timeout_sec, int, 0644);

static int major_num;
static int device_open_count = 0;

static int  rssi_buffer[BUFFER_SIZE];
static int  buf_head = 0;
static int  buf_tail = 0;
static DEFINE_SPINLOCK(buffer_lock);

static unsigned long last_seen_jiffies = 0;
static bool          beacon_ever_seen  = false;
static DEFINE_SPINLOCK(seen_lock);

static struct task_struct *ble_thread = NULL;

static inline void pt_put_le16(u16 val, void *dst)
{
    u8 *p = (u8 *)dst;
    p[0] = (u8)(val & 0xffu);
    p[1] = (u8)((val >> 8) & 0xffu);
}

static inline void pt_set_rcvtimeo(struct socket *sock, long ms)
{
    lock_sock(sock->sk);
    sock->sk->sk_rcvtimeo = msecs_to_jiffies(ms);
    release_sock(sock->sk);
}

static inline int pt_recvmsg(struct socket *sock, struct msghdr *msg,
                              struct kvec *iov, size_t size, int flags)
{
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 7, 0)
    iov_iter_kvec(&msg->msg_iter, ITER_DEST, iov, 1, size);
    return sock_recvmsg(sock, msg, flags);
#else
    return kernel_recvmsg(sock, msg, iov, 1, size, flags);
#endif
}

static void push_rssi(int rssi)
{
    unsigned long flags;
    spin_lock_irqsave(&buffer_lock, flags);
    rssi_buffer[buf_head] = rssi;
    buf_head = (buf_head + 1) % BUFFER_SIZE;
    if (buf_head == buf_tail)
        buf_tail = (buf_tail + 1) % BUFFER_SIZE;
    spin_unlock_irqrestore(&buffer_lock, flags);
}

static int pop_latest_rssi(int *rssi)
{
    unsigned long flags;
    int ret = 0;
    spin_lock_irqsave(&buffer_lock, flags);
    if (buf_head == buf_tail) {
        ret = -1;
    } else {
        int idx = (buf_head - 1 + BUFFER_SIZE) % BUFFER_SIZE;
        *rssi = rssi_buffer[idx];
    }
    spin_unlock_irqrestore(&buffer_lock, flags);
    return ret;
}

static u8 parsed_mac[6];
static int parse_mac_string(const char *mac_str, u8 *mac)
{
    int m[6], count = sscanf(mac_str, "%x:%x:%x:%x:%x:%x", &m[0], &m[1], &m[2], &m[3], &m[4], &m[5]);
    if (count == 6) {
        int i;
        for (i = 0; i < 6; i++) mac[i] = (u8)m[i];
        return 0;
    }
    return -EINVAL;
}

static int hci_send_raw(struct socket *sock, u16 opcode, const void *param, u8 plen)
{
    u8           buf[260];
    struct kvec  iov;
    struct msghdr msg;
    int          ret;

    buf[0] = PT_HCI_CMD_PKT;
    pt_put_le16(opcode, &buf[1]);
    buf[3] = plen;
    if (plen > 0 && param)
        memcpy(&buf[4], param, plen);

    iov.iov_base = buf;
    iov.iov_len  = 4 + (size_t)plen;

    memset(&msg, 0, sizeof(msg));
    ret = kernel_sendmsg(sock, &msg, &iov, 1, iov.iov_len);

    if (ret < 0)
        pr_warn("pico_tracker: hci_send_raw opcode=0x%04x failed: %d\n", opcode, ret);
    
    return ret;
}

static int ble_scan_thread_fn(void *data)
{
    struct socket           *sock = NULL;
    struct pt_sockaddr_hci   addr;
    struct pt_le_scan_param_cp  scan_param;
    struct pt_le_scan_enable_cp scan_enable;
    
    /* 解除靜音的 Event Mask */
    u8 evt_mask[8]    = { 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x3f };
    u8 le_evt_mask[8] = { 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff };
    
    int ret;
    u8  rx_buf[260];

    ret = sock_create_kern(&init_net, AF_BLUETOOTH, SOCK_RAW, BTPROTO_HCI, &sock);
    if (ret < 0) return ret;

    memset(&addr, 0, sizeof(addr));
    addr.hci_family  = AF_BLUETOOTH;
    addr.hci_dev     = (unsigned short)hci_dev_id;
    addr.hci_channel = PT_HCI_CHANNEL_USER;

    ret = kernel_bind(sock, (pt_bind_sa_t *)&addr, (int)sizeof(addr));
    if (ret < 0) {
        sock_release(sock);
        return ret;
    }

    pt_set_rcvtimeo(sock, 500); /* 500ms 超時，避免無窮阻塞 */

    /* 1. Reset 硬體 */
    pr_info("pico_tracker: Sending HCI_Reset to wake up hardware...\n");
    hci_send_raw(sock, PT_HCI_OP_RESET, NULL, 0);
    msleep(500);

    /* 2. 解除封印：讓硬體將 BLE 事件上報給 Kernel */
    pr_info("pico_tracker: Unmuting LE events in hardware...\n");
    hci_send_raw(sock, PT_HCI_OP_SET_EVENT_MASK, evt_mask, 8);
    msleep(50);
    hci_send_raw(sock, PT_HCI_OP_LE_SET_EVENT_MASK, le_evt_mask, 8);
    msleep(50);

    /* 3. 停止舊掃描 */
    scan_enable.enable     = 0x00;
    scan_enable.filter_dup = 0x00;
    hci_send_raw(sock, PT_HCI_OP_LE_SET_SCAN_ENABLE, &scan_enable, (u8)sizeof(scan_enable));
    msleep(100);

    /* 4. 設定掃描參數 */
    memset(&scan_param, 0, sizeof(scan_param));
    scan_param.type             = 0x01;
    scan_param.interval         = cpu_to_le16(0x00A0u);
    scan_param.window           = cpu_to_le16(0x0050u);
    scan_param.own_address_type = 0x00;
    scan_param.filter_policy    = 0x00;
    hci_send_raw(sock, PT_HCI_OP_LE_SET_SCAN_PARAM, &scan_param, (u8)sizeof(scan_param));
    msleep(100);

    /* 5. 啟動掃描 */
    scan_enable.enable     = 0x01;
    scan_enable.filter_dup = 0x00;
    hci_send_raw(sock, PT_HCI_OP_LE_SET_SCAN_ENABLE, &scan_enable, (u8)sizeof(scan_enable));

    pr_info("pico_tracker: BLE scan requested (target='%s')\n", strlen(target_mac) > 0 ? target_mac : target_name);

    u8  dynamic_target_mac[6] = {0};
    bool dynamic_mac_set = false;

    while (!kthread_should_stop()) {
        struct kvec   iov = { .iov_base = rx_buf, .iov_len = sizeof(rx_buf) };
        struct msghdr msg;
        int i, offset;
        u8  num_reports;

        /* ── 獨立的斷線偵測邏輯（不受環境噪音干擾） ── */
        {
            unsigned long flags;
            bool          ever_seen;
            unsigned long last;

            spin_lock_irqsave(&seen_lock, flags);
            ever_seen = beacon_ever_seen;
            last      = last_seen_jiffies;
            spin_unlock_irqrestore(&seen_lock, flags);

            /* 若曾看見過目標，且超時 */
            if (ever_seen && time_after(jiffies, last + msecs_to_jiffies((unsigned long)disconnect_timeout_sec * 1000UL))) {
                
                /* 防洗頻：將狀態重置，只發一次斷線警告 */
                spin_lock_irqsave(&seen_lock, flags);
                beacon_ever_seen = false;
                spin_unlock_irqrestore(&seen_lock, flags);

                push_rssi(DISCONNECT_SENTINEL);
                pr_warn("pico_tracker: [ALERT] Target lost (timeout > %ds). Sentinel pushed.\n", disconnect_timeout_sec);
            }
        }

        /* ── 接收硬體封包 ── */
        memset(&msg, 0, sizeof(msg));
        ret = pt_recvmsg(sock, &msg, &iov, sizeof(rx_buf), 0);

        if (ret == -EAGAIN || ret == -EWOULDBLOCK || ret == -ETIME) {
            continue; /* 超時沒關係，繼續迴圈執行斷線檢查 */
        }

        /* ── 檢查 ACK 狀態碼（只報錯） ── */
        if (ret >= 6 && rx_buf[0] == PT_HCI_EVENT_PKT && rx_buf[1] == 0x0E) {
            u16 op = (rx_buf[4] | (rx_buf[5] << 8));
            u8  status = rx_buf[6];
            if (status != 0x00) {
                pr_warn_ratelimited("pico_tracker: Hardware ACK Warning -> Opcode 0x%04X, Status 0x%02X\n", op, status);
            }
        }

        /* ── 解析 BLE 廣播封包 ── */
        if (ret < 5 || rx_buf[0] != PT_HCI_EVENT_PKT || rx_buf[1] != PT_HCI_EV_LE_META || rx_buf[3] != PT_HCI_EV_LE_ADV_REPORT)
            continue;

        num_reports = rx_buf[4];
        offset = 5;

        for (i = 0; i < (int)num_reports; i++) {
            u8 data_len;
            u8 *ad_data;
            s8 rssi_raw;

            if (offset + 9 > ret) break;
            data_len = rx_buf[offset + 8];
            if (offset + 9 + (int)data_len >= ret) break;

            ad_data  = &rx_buf[offset + 9];
            rssi_raw = (s8)rx_buf[offset + 9 + (int)data_len];
            u8 *addr = &rx_buf[offset + 2];

            /* (可選) 印出看到的所有設備名稱幫助 Debug */
            /*
            int dbg_pos = 0;
            while (dbg_pos < data_len) {
                u8 len = ad_data[dbg_pos];
                if (len == 0 || dbg_pos + 1 + len > data_len) break;
                u8 type = ad_data[dbg_pos + 1];
                if (type == PT_AD_TYPE_COMPLETE_NAME || type == PT_AD_TYPE_SHORT_NAME) {
                    char name_buf[32] = {0};
                    int nlen = len - 1;
                    if (nlen > 31) nlen = 31;
                    memcpy(name_buf, &ad_data[dbg_pos + 2], nlen);
                    // pr_info_ratelimited("pico_tracker: Saw Device: '%s' (RSSI: %d)\n", name_buf, rssi_raw);
                }
                dbg_pos += len + 1;
            }
            */

            bool matched = false;

            /* 比對目標 MAC 或 名稱 */
            if (strlen(target_mac) > 0) {
                if (addr[5] == parsed_mac[0] && addr[4] == parsed_mac[1] &&
                    addr[3] == parsed_mac[2] && addr[2] == parsed_mac[3] &&
                    addr[1] == parsed_mac[4] && addr[0] == parsed_mac[5]) {
                    matched = true;
                }
            } else if (strlen(target_name) > 0) {
                /* 動態 MAC 快取機制 */
                if (dynamic_mac_set &&
                    addr[5] == dynamic_target_mac[0] && addr[4] == dynamic_target_mac[1] &&
                    addr[3] == dynamic_target_mac[2] && addr[2] == dynamic_target_mac[3] &&
                    addr[1] == dynamic_target_mac[4] && addr[0] == dynamic_target_mac[5]) {
                    matched = true;
                } else {
                    int pos = 0;
                    int target_len = strlen(target_name);
                    while (pos < data_len) {
                        u8 len = ad_data[pos];
                        if (len == 0 || pos + 1 + len > data_len) break;
                        u8 type = ad_data[pos + 1];
                        if (type == PT_AD_TYPE_COMPLETE_NAME || type == PT_AD_TYPE_SHORT_NAME) {
                            int name_len = len - 1;
                            if (name_len >= target_len && memcmp(&ad_data[pos + 2], target_name, target_len) == 0) {
                                matched = true;
                                dynamic_target_mac[0] = addr[5]; dynamic_target_mac[1] = addr[4];
                                dynamic_target_mac[2] = addr[3]; dynamic_target_mac[3] = addr[2];
                                dynamic_target_mac[4] = addr[1]; dynamic_target_mac[5] = addr[0];
                                dynamic_mac_set = true;
                                pr_info("pico_tracker: Target Locked! MAC=%02X:%02X:%02X:%02X:%02X:%02X\n",
                                        addr[5], addr[4], addr[3], addr[2], addr[1], addr[0]);
                                break;
                            }
                        }
                        pos += len + 1;
                    }
                }
            }

            /* 如果是目標裝置，更新最後看見的時間，並存入 RSSI */
            if (matched) {
                unsigned long flags;
                spin_lock_irqsave(&seen_lock, flags);
                last_seen_jiffies = jiffies;
                beacon_ever_seen  = true;
                spin_unlock_irqrestore(&seen_lock, flags);

                push_rssi((int)rssi_raw);
            }
            offset += 1 + 1 + 6 + 1 + (int)data_len + 1;
        }
    }

    /* 結束時關閉掃描 */
    scan_enable.enable = 0x00;
    hci_send_raw(sock, PT_HCI_OP_LE_SET_SCAN_ENABLE, &scan_enable, (u8)sizeof(scan_enable));
    sock_release(sock);
    return 0;
}

static int pico_dev_open(struct inode *inodep, struct file *filep) { device_open_count++; return 0; }
static int pico_dev_release(struct inode *inodep, struct file *filep) { device_open_count--; return 0; }
static ssize_t pico_dev_write(struct file *filep, const char __user *buffer, size_t len, loff_t *offset)
{
    int rssi_val;
    if (len < sizeof(int)) return -EINVAL;
    if (copy_from_user(&rssi_val, buffer, sizeof(int))) return -EFAULT;
    push_rssi(rssi_val);
    return sizeof(int);
}

static long pico_dev_ioctl(struct file *filep, unsigned int cmd, unsigned long arg)
{
    int rssi = 0;
    switch (cmd) {
    case PICO_GET_RSSI:
        if (pop_latest_rssi(&rssi) == -1) return -ENODATA;
        if (copy_to_user((int __user *)arg, &rssi, sizeof(rssi))) return -EFAULT;
        break;
    default: return -ENOTTY;
    }
    return 0;
}

static const struct file_operations fops = {
    .owner           = THIS_MODULE,
    .open            = pico_dev_open,
    .release         = pico_dev_release,
    .write           = pico_dev_write,
    .unlocked_ioctl  = pico_dev_ioctl,
};

static int __init pico_tracker_init(void)
{
    int ret;
    if (strlen(target_mac) > 0) {
        if (parse_mac_string(target_mac, parsed_mac) < 0) return -EINVAL;
    }

    major_num = register_chrdev(0, DEVICE_NAME, &fops);
    if (major_num < 0) return major_num;

    ble_thread = kthread_run(ble_scan_thread_fn, NULL, "pico_ble_scan");
    if (IS_ERR(ble_thread)) {
        ret = PTR_ERR(ble_thread);
        unregister_chrdev(major_num, DEVICE_NAME);
        return ret;
    }
    return 0;
}

static void __exit pico_tracker_exit(void)
{
    if (ble_thread) { kthread_stop(ble_thread); ble_thread = NULL; }
    unregister_chrdev(major_num, DEVICE_NAME);
}

module_init(pico_tracker_init);
module_exit(pico_tracker_exit);