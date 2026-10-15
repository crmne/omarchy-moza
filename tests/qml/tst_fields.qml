import QtQuick
import QtTest
import "../../controls"

// Key-event fields. Run by tests/test_qml.py with stand-ins for the shell kit.
Item {
  id: scene
  width: 600; height: 400

  property var modified: []
  property var edits: []
  property int finished: 0

  NumberKeyField {
    id: number
    y: 0
    from: 0; to: 100; value: 42; stepSize: 5
    onModified: value => scene.modified = scene.modified.concat([value])
  }
  NumberKeyField {
    id: signedNumber
    y: 80
    from: -10; to: 10; value: 0
    onModified: value => scene.modified = scene.modified.concat([value])
  }
  KeyField {
    id: text
    y: 160; width: 200
    value: "#112233"
    maximumLength: 7
    allowedCharacters: /[#0-9a-fA-F]/
    onTextEdited: scene.edits = scene.edits.concat([text])
    onEditingFinished: scene.finished++
  }
  Item { id: elsewhere; y: 240; width: 10; height: 10; activeFocusOnTab: true }

  TestCase {
    name: "Fields"
    when: windowShown

    function init() {
      elsewhere.forceActiveFocus()
      // A model update resets what the field shows, as the backend echo does.
      number.value = -1; number.value = 42
      signedNumber.value = 1; signedNumber.value = 0
      text.value = "#112233"
      text.text = text.value
      scene.modified = []; scene.edits = []; scene.finished = 0
    }

    // Click the middle of the field, away from the step arrows.
    function focusNumber(field) { mouseClick(field, field.width / 2 - 20, field.height / 2) }

    function test_typing_replaces_and_commits_on_return() {
      focusNumber(number)
      keyClick(Qt.Key_7); keyClick(Qt.Key_5)
      compare(number.displayValue, 42)
      compare(scene.modified, [])
      keyClick(Qt.Key_Return)
      compare(scene.modified, [75])
      compare(number.displayValue, 75)
      compare(number.value, 42, "the caller's binding is left alone")
    }

    function test_commit_clamps_and_focus_loss_finishes() {
      focusNumber(number)
      keyClick(Qt.Key_9); keyClick(Qt.Key_9); keyClick(Qt.Key_9); keyClick(Qt.Key_9)
      elsewhere.forceActiveFocus()
      compare(scene.modified, [100])
    }

    function test_up_down_step_and_clamp() {
      focusNumber(number)
      keyClick(Qt.Key_Up)
      keyClick(Qt.Key_Down); keyClick(Qt.Key_Down)
      compare(scene.modified, [47, 42, 37])
      number.value = 98
      keyClick(Qt.Key_Up); keyClick(Qt.Key_Up)
      compare(scene.modified, [47, 42, 37, 100])
    }

    function test_step_arrows() {
      mouseClick(number, number.width - 14, 8)
      mouseClick(number, number.width - 14, number.height - 8)
      mouseClick(number, number.width - 14, number.height - 8)
      compare(scene.modified, [47, 42, 37])
      number.value = 100
      mouseClick(number, number.width - 14, 8)
      compare(scene.modified, [47, 42, 37], "the up arrow is unavailable at the maximum")
    }

    function test_backspace_escape_and_empty_restore() {
      focusNumber(number)
      keyClick(Qt.Key_Backspace)
      keyClick(Qt.Key_Return)
      compare(scene.modified, [])
      compare(number.displayValue, 42)
      keyClick(Qt.Key_8)
      keyClick(Qt.Key_Escape)
      elsewhere.forceActiveFocus()
      compare(scene.modified, [])
      compare(number.displayValue, 42)
    }

    function test_minus_only_when_range_is_negative() {
      focusNumber(number)
      keyClick(Qt.Key_Minus); keyClick(Qt.Key_3); keyClick(Qt.Key_Return)
      compare(scene.modified, [3])
      focusNumber(signedNumber)
      keyClick(Qt.Key_Minus); keyClick(Qt.Key_4); keyClick(Qt.Key_Return)
      compare(scene.modified, [3, -4])
    }

    function test_ctrl_v_and_letters_do_nothing() {
      focusNumber(number)
      keyClick(Qt.Key_V, Qt.ControlModifier)
      keyClick(Qt.Key_A)
      keyClick(Qt.Key_Return)
      compare(scene.modified, [])
      text.forceActiveFocus()
      keyClick(Qt.Key_V, Qt.ControlModifier)
      compare(text.text, "#112233")
    }

    function test_wheel_is_not_handled() {
      var before = number.displayValue
      mouseWheel(number, number.width / 2, number.height - 10, 0, 120)
      compare(number.displayValue, before)
      compare(scene.modified, [])
    }

    function test_text_field_typing_limit_and_filter() {
      text.forceActiveFocus()
      keyClick(Qt.Key_Backspace, Qt.ControlModifier)
      compare(text.text, "")
      keyClick(Qt.Key_NumberSign, Qt.ShiftModifier)
      keyClick(Qt.Key_A); keyClick(Qt.Key_Z); keyClick(Qt.Key_B)
      compare(text.text, "#ab", "z is not a hex digit")
      for (var i = 0; i < 8; i++) keyClick(Qt.Key_1)
      compare(text.text, "#ab1111", "seven characters at most")
      keyClick(Qt.Key_Backspace)
      compare(text.text, "#ab111")
      verify(scene.edits.length > 0)
      keyClick(Qt.Key_Return)
      compare(scene.finished, 1)
    }

    function test_text_field_follows_model_only_when_idle() {
      text.forceActiveFocus()
      keyClick(Qt.Key_Backspace)
      text.value = "#445566"
      compare(text.text, "#11223", "a model update does not clobber typing")
      elsewhere.forceActiveFocus()
      compare(scene.finished, 1)
      text.value = "#778899"
      compare(text.text, "#778899")
    }
  }
}
