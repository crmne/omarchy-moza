pragma Singleton
import QtQuick

// Test stand-in for the Omarchy shell's Style, which needs Quickshell.
QtObject {
  property real cornerRadius: 6
  property QtObject font: QtObject {
    property string family: "monospace"
    property real body: 14
    property real bodySmall: 12
    property real caption: 11
  }
  property QtObject spacing: QtObject {
    property int md: 6
    property int controlPaddingX: 10
    property int controlPaddingY: 6
    property int inputPaddingY: 7
    property int controlHeight: 28
    property int numberFieldWidth: 120
  }
  function space(px) { return Math.round(px) }
  function spaceReal(px) { return px }
  function controlFill(focused, hot, foreground, accent) { return focused ? "#30ffffff" : (hot ? "#20ffffff" : "#10ffffff") }
  function selectionFillFor(foreground, accent) { return "#40ff8800" }
}
