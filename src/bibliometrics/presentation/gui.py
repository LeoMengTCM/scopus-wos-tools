"""GUI launcher that keeps the customtkinter dependency optional and lazy."""


def main() -> int:
    try:
        import customtkinter  # noqa: F401
    except ImportError:
        print("错误: 缺少 customtkinter 库")
        print("\n请先安装:")
        print("  pip install .[gui]")
        print("\n或者使用原命令:")
        print("  pip3 install customtkinter")
        print("  pip3 install --break-system-packages customtkinter")
        return 1

    from ._app import MultiDatabaseGUI

    app = MultiDatabaseGUI()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
