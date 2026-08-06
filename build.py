import os
import sys
import subprocess
import shutil


def check_pyinstaller():
    try:
        import PyInstaller
        return True
    except ImportError:
        return False


def check_nuitka():
    try:
        import nuitka
        return True
    except ImportError:
        return False


def build_with_pyinstaller():
    project_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(project_dir, "main.py")
    dist_dir = os.path.join(project_dir, "dist")
    build_dir = os.path.join(project_dir, "build")

    resources_dir = os.path.join(project_dir, "resources")
    images_dir = os.path.join(project_dir, "ys", "xys", "images")
    icon_path = os.path.join(project_dir, "favicon.ico")

    data_args = []
    if os.path.exists(resources_dir):
        data_args = ["--add-data", f"{resources_dir};resources"]
    # 把 favicon.ico 作为数据文件嵌入，供运行时设置窗口图标
    if os.path.exists(icon_path):
        data_args.append("--add-data")
        data_args.append(f"{icon_path};.")
    # 包含设计元素图片目录
    if os.path.exists(images_dir):
        data_args.append("--add-data")
        data_args.append(f"{images_dir};ys/xys/images")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onefile",
        "--name=为投个屏",
        f"--distpath={dist_dir}",
        f"--workpath={build_dir}",
        f"--specpath={project_dir}",
        "--hidden-import=cv2",
        "--hidden-import=numpy",
        "--hidden-import=websockets",
        "--hidden-import=core.hdc_client",
        "--hidden-import=core.cast_engine",
        "--hidden-import=core.input_manager",
        "--hidden-import=core.audio_manager",
        "--hidden-import=core.hdc_cast_service",
        "--hidden-import=core.web_cast_server",
        "--hidden-import=ui.styles",
        "--hidden-import=ui.main_window",
        "--hidden-import=ui.device_page",
        "--hidden-import=ui.cast_page",
        "--hidden-import=ui.extensions_page",
        "--hidden-import=ui.settings_page",
        "--hidden-import=ui.performance_page",
        "--hidden-import=ui.toolbox_page",
    ]

    if os.path.exists(icon_path):
        cmd.append(f"--icon={icon_path}")

    cmd.extend(data_args)
    cmd.append(main_script)

    print("开始使用 PyInstaller 打包...")
    print("命令:", " ".join(cmd))

    try:
        subprocess.check_call(cmd, cwd=project_dir)
        print("\n✅ 打包完成！")
        print(f"输出目录: {dist_dir}")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 打包失败: {e}")
        sys.exit(1)


def build_with_nuitka():
    project_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(project_dir, "main.py")
    resources_dir = os.path.join(project_dir, "resources")
    output_dir = os.path.join(project_dir, "dist")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--onefile",
        "--windows-console-mode=disable",
        "--output-dir=" + output_dir,
        "--output-filename=为投个屏.exe",
        "--enable-plugin=pyside6",
        "--follow-imports",
        "--include-package=core",
        "--include-package=ui",
        "--include-module=cv2",
        "--include-package=numpy",
        # 排除非必要模块以减小体积
        "--nofollow-import-to=*.tests",
        "--nofollow-import-to=*.test",
        "--nofollow-import-to=_pyinstaller_hooks_contrib",
        # 网页投屏与投屏引擎在运行时会被 ui.cast_page 引用，不能排除
        "--nofollow-import-to=cv2.data",
        "--nofollow-import-to=cv2.samples",
        "--nofollow-import-to=cv2.dnn",
        "--nofollow-import-to=cv2.aruco",
        "--nofollow-import-to=cv2.barcode",
        "--nofollow-import-to=cv2.ccm",
        "--nofollow-import-to=cv2.cuda",
        "--nofollow-import-to=cv2.fisheye",
        "--nofollow-import-to=cv2.flann",
        "--nofollow-import-to=cv2.mcc",
        "--nofollow-import-to=cv2.ocl",
        "--nofollow-import-to=cv2.ogl",
        "--nofollow-import-to=cv2.segmentation",
        "--nofollow-import-to=PySide6.QtPdf",
        "--nofollow-import-to=PySide6.QtPdfWidgets",
        "--nofollow-import-to=PySide6.QtWebEngineCore",
        "--nofollow-import-to=PySide6.QtWebEngineWidgets",
        "--nofollow-import-to=PySide6.QtQml",
        "--nofollow-import-to=PySide6.QtQuick",
        "--nofollow-import-to=PySide6.QtQuick3D",
        "--nofollow-import-to=PySide6.QtWebChannel",
        "--nofollow-import-to=PySide6.QtWebSockets",
        "--nofollow-import-to=PySide6.QtDesigner",
        "--nofollow-import-to=PySide6.QtHelp",
        "--nofollow-import-to=PySide6.QtMultimedia",
        "--nofollow-import-to=PySide6.Qt3DCore",
        "--nofollow-import-to=PySide6.Qt3DRender",
        "--nofollow-import-to=PySide6.QtCharts",
        "--nofollow-import-to=PySide6.QtDataVisualization",
        "--nofollow-import-to=PySide6.QtSql",
        "--nofollow-import-to=PySide6.QtTest",
        "--nofollow-import-to=PySide6.QtXml",
        "--nofollow-import-to=PySide6.QtPrintSupport",
        "--nofollow-import-to=PySide6.QtBluetooth",
        "--nofollow-import-to=PySide6.QtPositioning",
        "--nofollow-import-to=PySide6.QtSensors",
        "--nofollow-import-to=PySide6.QtSerialPort",
        "--nofollow-import-to=PySide6.QtSerialBus",
        "--nofollow-import-to=PySide6.QtNfc",
        "--assume-yes-for-downloads",
        "--show-progress",
        "--show-memory",
        "--jobs=4",
        "--lto=no",
    ]

    icon_path = os.path.join(project_dir, "favicon.ico")
    if os.path.exists(icon_path):
        cmd.append("--windows-icon-from-ico=" + icon_path)
        # 同时把 favicon.ico 作为数据文件嵌入，供运行时设置窗口图标
        cmd.append(f"--include-data-files={icon_path}=favicon.ico")

    # 显式包含所有资源文件，避免 --include-data-dir 遗漏子目录
    if os.path.exists(resources_dir):
        for root, dirs, files in os.walk(resources_dir):
            rel_dir = os.path.relpath(root, project_dir)
            for f in files:
                src = os.path.join(root, f)
                dst = os.path.join(rel_dir, f).replace("\\", "/")
                cmd.append(f"--include-data-files={src}={dst}")

    # 包含设计元素图片目录
    images_dir = os.path.join(project_dir, "ys", "xys", "images")
    if os.path.exists(images_dir):
        for root, dirs, files in os.walk(images_dir):
            rel_dir = os.path.relpath(root, project_dir)
            for f in files:
                src = os.path.join(root, f)
                dst = os.path.join(rel_dir, f).replace("\\", "/")
                cmd.append(f"--include-data-files={src}={dst}")

    cmd.append(main_script)

    print("开始使用 Nuitka 打包...")
    print("命令:", " ".join(cmd))
    print()

    try:
        subprocess.check_call(cmd, cwd=project_dir)
        print("\n✅ 打包完成！")
        print(f"输出目录: {output_dir}")
        exe_path = os.path.join(output_dir, "为投个屏.exe")
        if os.path.exists(exe_path):
            print(f"文件大小: {os.path.getsize(exe_path) / 1024 / 1024:.1f} MB")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 打包失败: {e}")
        sys.exit(1)


def build():
    # Nuitka 不支持嵌入式 Python 发行版，使用 PyInstaller
    if check_pyinstaller():
        build_with_pyinstaller()
    elif check_nuitka():
        build_with_nuitka()
    else:
        print("❌ 未找到 PyInstaller 或 Nuitka，请先安装")
        sys.exit(1)


if __name__ == "__main__":
    build()
