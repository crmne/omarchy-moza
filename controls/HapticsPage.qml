import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as UI

Column {
  id: root
  required property var service
  spacing: Style.space(16)
  readonly property var rev: service.rev
  readonly property var module: rev.haptics || ({})
  readonly property var config: service.haptics
  property string pedal: "brake"
  // Pit House's tabs and effects, in its order. Ranges match the Rust validation.
  readonly property var pedals: [{key: "clutch", label: "Clutch"}, {key: "brake", label: "Brake"}, {key: "throttle", label: "Throttle"}]
  readonly property var effects: [
    {key: "engine", title: "Engine vibration", text: "Frequency rises with RPM across the range.", rpm: true},
    {key: "gear_shift", title: "Gear shift", text: "A short kick on every gear change."},
    {key: "tc", title: "Traction control", text: "While traction control cuts power."},
    {key: "abs", title: "ABS", text: "While ABS releases the brakes.", pedals: ["brake"]},
    {key: "wheel_spin", title: "Wheel spin", text: "When a wheel spins under throttle."},
    {key: "lockup", title: "Wheel lockup", text: "When a wheel locks under braking.", pedals: ["brake"]},
    {key: "brake_threshold", title: "Brake threshold", text: "Past this much brake pedal travel.", pedals: ["brake"], trigger: true},
    {key: "bite", title: "Clutch bite point", text: "Around this point of clutch travel. Smoothness widens the zone.", pedals: ["clutch"], trigger: true, smoothness: true},
    {key: "road", title: "Road texture", text: "Bumps and kerbs, from suspension movement.", noFrequency: true}
  ]
  function playing(effect) {
    return (module.active || []).some(item => item[0] === root.pedal && item[1] === effect)
  }

  Card {
    Label { width: parent.width; text: root.module.connected ? (root.rev.game || "Ready for telemetry") : "Plug the pedal haptic module into this computer"; color: Commons.Color.accent; font.pixelSize: Style.font.bodySmall }
    UI.Toggle {
      width: parent.width; label: "Vibration"
      description: "Play effects on the pedals from live game telemetry"
      checked: !!root.config && root.config.enabled
      enabled: !!root.config
      foreground: Commons.Color.popups.text
      onClicked: root.service.setHapticsEnabled(!checked)
    }
    Label { width: parent.width; visible: !root.config; text: "Loading settings…"; font.pixelSize: Style.font.bodySmall; opacity: 0.55 }
    Label {
      width: parent.width
      text: "Effects need the game to report the input they follow. Engine vibration works in every supported game; see the README for what each game reports."
      font.pixelSize: Style.font.bodySmall; opacity: 0.55
    }
  }
  Card {
    visible: root.service.steam.games.length > 0
    Label { text: "ACC AND LE MANS ULTIMATE"; color: Commons.Color.accent; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1.1 }
    Label {
      width: parent.width; font.pixelSize: Style.font.bodySmall; opacity: 0.55
      text: "These games share telemetry only inside Proton. A small helper starts with the game when its Steam launch options include it. For Le Mans Ultimate, plugins must also be enabled."
    }
    Repeater {
      model: root.service.steam.games
      Label { required property var modelData; width: parent.width; text: (modelData.ready ? "●  " : "○  ") + modelData.name + (modelData.ready ? " · ready" : " · not set up") }
    }
    UI.Button {
      visible: root.service.steam.games.some(game => !game.ready)
      text: root.service.steam.steamRunning ? "Close Steam to set up" : "Set up launch options"
      enabled: !root.service.steam.steamRunning
      bordered: true; focusable: true
      onClicked: root.service.send({op: "steam_setup"})
    }
    Label {
      width: parent.width; visible: root.service.steam.games.some(game => !game.ready)
      text: "Adds the helper to each game's launch options, keeping your own, and enables LMU's plugins. Backups are saved next to each file. Steam must be closed, because it rewrites these settings when it exits."
      font.pixelSize: Style.font.bodySmall; opacity: 0.55
    }
  }
  Row {
    spacing: Style.space(4)
    Repeater {
      model: root.pedals
      UI.Button { required property var modelData; text: modelData.label; selected: root.pedal === modelData.key; focusable: true; fontSize: Style.font.bodySmall; onClicked: root.pedal = modelData.key }
    }
  }
  Repeater {
    model: root.config ? root.effects.filter(effect => !effect.pedals || effect.pedals.indexOf(root.pedal) !== -1) : []
    Card {
      id: card
      required property var modelData
      readonly property var settings: root.config[root.pedal][modelData.key]
      function set(key, value) { root.service.setHaptic(root.pedal, modelData.key, key, value) }
      Row {
        width: parent.width
        spacing: Style.space(10)
        Rectangle {
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(8); height: width; radius: width / 2
          color: Commons.Color.accent
          opacity: root.playing(card.modelData.key) ? 1 : 0.15
        }
        Column {
          width: parent.width - Style.space(18) - testButton.width - toggle.width - parent.spacing * 2
          spacing: Style.space(2)
          Label { width: parent.width; text: card.modelData.title; font.bold: true }
          Label { width: parent.width; text: card.modelData.text; font.pixelSize: Style.font.bodySmall; opacity: 0.55 }
        }
        UI.Button {
          id: testButton
          anchors.verticalCenter: parent.verticalCenter
          text: root.module.testing && root.module.testing[0] === root.pedal && root.module.testing[1] === card.modelData.key ? "Testing…" : "Test"
          enabled: !!root.module.connected && !root.module.testing
          bordered: true; focusable: true; fontSize: Style.font.bodySmall
          onClicked: root.service.testHaptic(root.pedal, card.modelData.key)
        }
        UI.ToggleSwitch {
          id: toggle
          anchors.verticalCenter: parent.verticalCenter
          checked: card.settings.enabled
          onToggled: card.set("enabled", !checked)
        }
      }
      Column {
        width: parent.width
        spacing: Style.space(8)
        opacity: card.settings.enabled ? 1 : 0.5
        HapticSlider { visible: !card.modelData.noFrequency; label: card.modelData.rpm ? "Top frequency (Hz)" : "Frequency (Hz)"; from: 10; to: 100; value: card.settings.frequency; onModified: value => card.set("frequency", value) }
        HapticSlider { label: "Intensity (%)"; from: 0; to: 100; value: card.settings.intensity; onModified: value => card.set("intensity", value) }
        HapticSlider { visible: !!card.modelData.trigger; label: "Trigger (% travel)"; from: 0; to: 100; value: card.settings.trigger; onModified: value => card.set("trigger", value) }
        HapticSlider { visible: !!card.modelData.smoothness; label: "Smoothness (%)"; from: 0; to: 100; value: card.settings.smoothness; onModified: value => card.set("smoothness", value) }
        Row {
          visible: !!card.modelData.rpm
          spacing: Style.space(24)
          NumberKeyField {
            label: "From (RPM)"; from: 0; to: card.settings.end - 100; stepSize: 100; value: card.settings.start
            foreground: Commons.Color.popups.text; fieldWidth: Style.space(120)
            onModified: value => card.set("start", value)
          }
          NumberKeyField {
            label: "To (RPM)"; from: card.settings.start + 100; to: 30000; stepSize: 100; value: card.settings.end
            foreground: Commons.Color.popups.text; fieldWidth: Style.space(120)
            onModified: value => card.set("end", value)
          }
        }
      }
    }
  }
}
