pragma Singleton
import QtQuick

QtObject {
  function controlSpec(state, foreground, accent) { return {width: 1, state: state} }
  function top(spec) { return spec.width }
  function right(spec) { return spec.width }
  function bottom(spec) { return spec.width }
  function left(spec) { return spec.width }
}
