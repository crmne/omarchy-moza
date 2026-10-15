pragma Singleton
import QtQuick

QtObject {
  property color foreground: "#e6d9db"
  property color accent: "#f38d70"
  property QtObject popups: QtObject { property color text: "#e6d9db" }
}
