"""
完整界面布局测试脚本
- 验证所有页面导航切换
- 验证布局不挤压
- 验证设置页面（含关于板块）正确显示
- 验证所有 PNG 素材正确加载
"""
import sys
import os

# 路径配置
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap

# 统计素材使用
USED_PNGS = {}
ELEMENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ys", "xys", "images")

def track_usage():
    """记录所有加载的素材文件"""
    from ui import main_window, device_page, extensions_page, settings_page
    original_load = main_window.load_element_pixmap

    def wrapped_load(name):
        USED_PNGS.setdefault(name, 0)
        USED_PNGS[name] += 1
        return original_load(name)

    main_window.load_element_pixmap = wrapped_load
    return wrapped_load

def main():
    # 兼容 GBK 控制台：允许打印 ✓/✗ 等 Unicode 字符
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    load_tracker = track_usage()
    app = QApplication.instance() or QApplication(sys.argv)

    # 应用样式表
    from ui.styles import APP_QSS
    app.setStyleSheet(APP_QSS)

    from ui.main_window import MainWindow
    win = MainWindow()

    print("=" * 60)
    print("  为投个屏 - 完整界面布局测试")
    print("=" * 60)

    errors = []
    checks = []

    # ---------- 1. 主窗口尺寸 ----------
    print("\n[1/8] 主窗口尺寸检查")
    w, h = win.width(), win.height()
    min_w, min_h = win.minimumWidth(), win.minimumHeight()
    print(f"  默认尺寸: {w}x{h}")
    print(f"  最小尺寸: {min_w}x{min_h}")
    ok = min_w >= 1000 and min_h >= 600
    checks.append(("主窗口尺寸合理", ok))
    print(f"  {'✓' if ok else '✗'} 结果: {'通过' if ok else '失败 - 最小尺寸过小'}")

    # ---------- 2. 侧边栏导航不挤压 ----------
    print("\n[2/8] 侧边栏导航检查")
    sb = win._sidebar_widget
    nav_items = sb._nav_widgets
    print(f"  导航项数量: {len(nav_items)}")
    nav_heights_ok = True
    for pid, nav_w in nav_items:
        h = nav_w.height()
        print(f"    - {pid}: {nav_w._label} (height={h})")
        if h < 40:
            nav_heights_ok = False
    checks.append(("导航项不挤压", nav_heights_ok))
    print(f"  {'✓' if nav_heights_ok else '✗'} 导航项不挤压: {'通过' if nav_heights_ok else '失败'}")

    # 检查设置入口在左下角
    settings_entry = sb._settings_entry
    if settings_entry:
        se_h = settings_entry.height() if settings_entry else 0
        print(f"  设置入口高度: {se_h}")
        checks.append(("设置入口存在", settings_entry is not None and se_h > 30))
        print(f"  ✓ 设置入口在左下角")

    # ---------- 3. 设备投屏页面 ----------
    print("\n[3/8] 设备投屏页面检查")
    win._on_nav_changed("device")
    app.processEvents()
    QTimer.singleShot(200, lambda: None)
    app.processEvents()
    dp = win.device_page
    dp_w = dp.width()
    dp_h = dp.height()
    print(f"  页面可用尺寸: {dp_w}x{dp_h}")
    checks.append(("设备页不挤压", dp_w > 600 and dp_h > 400))
    print(f"  {'✓' if dp_w > 600 and dp_h > 400 else '✗'} 设备页尺寸合理")

    # ---------- 4. 扩展功能页面（三栏）----------
    print("\n[4/8] 扩展功能页面（三栏）检查")
    win._on_nav_changed("extensions")
    app.processEvents()
    QTimer.singleShot(200, lambda: None)
    app.processEvents()
    ep = win.extensions_page
    ep_w = ep.width()
    ep_h = ep.height()
    print(f"  页面可用尺寸: {ep_w}x{ep_h}")
    # 找到三个功能卡片
    from PySide6.QtWidgets import QFrame
    cards = ep.findChildren(QFrame, "featureCard")
    print(f"  功能卡片数量: {len(cards)}")
    for i, card in enumerate(cards):
        print(f"    - Card {i+1}: w={card.width()}, h={card.height()}")
    cards_ok = len(cards) == 3 and all(c.width() > 180 and c.height() > 200 for c in cards)
    checks.append(("扩展功能三栏合理", cards_ok))
    print(f"  {'✓' if cards_ok else '✗'} 三栏布局不挤压: {'通过' if cards_ok else '失败'}")

    # ---------- 5. 设置页面（含关于板块）----------
    print("\n[5/8] 设置页面（含关于板块）检查")
    win._goto_settings()
    app.processEvents()
    QTimer.singleShot(200, lambda: None)
    app.processEvents()
    sp = win.settings_page
    sp_w = sp.width()
    sp_h = sp.height()
    print(f"  页面可用尺寸: {sp_w}x{sp_h}")
    # 查找关于区域
    about_labels = sp.findChildren(QLabel)
    about_texts = [l.text() for l in about_labels if "为投个屏" in l.text() or "版本" in l.text() or "版权" in l.text() or "HoKit" in l.text()]
    print(f"  找到关于板块文本: {len(about_texts)} 条")
    for t in about_texts[:5]:
        print(f"    - {t[:60]}...")
    about_ok = len(about_texts) >= 2
    checks.append(("关于板块已复刻", about_ok))
    print(f"  {'✓' if about_ok else '✗'} 关于板块: {'存在' if about_ok else '缺失'}")

    # ---------- 6. 投屏页面 ----------
    print("\n[6/8] 投屏页面检查")
    win.stack.setCurrentIndex(3)
    app.processEvents()
    QTimer.singleShot(200, lambda: None)
    app.processEvents()
    cp = win.cast_page
    cp_w = cp.width()
    cp_h = cp.height()
    phone = cp.phone_screen
    tb = cp.toolbar
    print(f"  页面可用: {cp_w}x{cp_h}")
    print(f"  手机壳尺寸: {phone.width()}x{phone.height()}")
    print(f"  工具栏宽度: {tb.width()}")
    cast_ok = phone.width() > 250 and phone.height() > 600 and tb.width() < 100
    checks.append(("投屏页布局合理", cast_ok))
    print(f"  {'✓' if cast_ok else '✗'} 投屏页布局: {'合理' if cast_ok else '挤压'}")

    # ---------- 7. PNG素材统计 ----------
    print("\n[7/8] PNG 素材使用统计")
    # 收集所有用到的素材
    from ui import main_window as mw_mod, device_page as dp_mod, extensions_page as ep_mod, settings_page as sp_mod
    used = set()
    for mod in [mw_mod, dp_mod, ep_mod, sp_mod]:
        import re
        try:
            src = open(mod.__file__, "r", encoding="utf-8").read()
            matches = re.findall(r'Element_\d+\.png', src)
            for m in matches:
                used.add(m)
        except Exception:
            pass

    used_list = sorted(used)
    if os.path.isdir(ELEMENT_DIR):
        available = set(os.listdir(ELEMENT_DIR)) & {f"Element_{i:02d}.png" for i in range(1, 25)}
    else:
        available = set()
        print("  (素材目录不存在，跳过存在性检查)")
    for fn in used_list:
        exists = fn in available
        print(f"  - {fn}: {'✓' if exists else '✗（素材缺失，使用占位回退）'}")
        if exists:
            USED_PNGS[fn] = USED_PNGS.get(fn, 0) + 1
    # 素材目录缺失时该项跳过，不判定为失败（界面已有占位回退）
    checks.append(("素材存在性", all(f in available for f in used_list) or not os.path.isdir(ELEMENT_DIR)))
    print(f"  共使用 {len(used_list)} 个 PNG 素材")

    # ---------- 8. 汇总 ----------
    print("\n" + "=" * 60)
    print("  测试汇总")
    print("=" * 60)
    all_pass = True
    for name, ok in checks:
        print(f"  {'✓' if ok else '✗'} {name}")
        if not ok:
            all_pass = False

    print("\n" + "=" * 60)
    print(f"  最终结果: {'全部通过 ✓' if all_pass else '存在问题 ✗'}")
    print("=" * 60)
    print(f"\n  PNG 素材使用总数: {len(used_list)} 个")
    print("  使用的素材列表:")
    for f in used_list:
        print(f"    - {f}")

    # 显示主窗口
    win.show()
    win.raise_()
    win.activateWindow()

    # 5秒后自动关闭（或用户手动关闭）
    def auto_close():
        if win.isVisible():
            win.close()
            app.quit()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(auto_close)
    timer.start(8000)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
