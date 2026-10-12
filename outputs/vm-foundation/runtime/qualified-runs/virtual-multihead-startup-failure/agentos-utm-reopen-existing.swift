import AppKit
let app = URL(fileURLWithPath: "/Applications/UTM.app")
_ = try NSWorkspace.shared.launchApplication(at: app, options: [], configuration: [.arguments: ["-ApplePersistenceIgnoreState", "YES"]])
