import Foundation
import Security

enum DesktopError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self { case .message(let value): return value }
    }
}

enum Credential {
    static func load() throws -> String {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "dev.openartifact.desktop",
            kSecAttrAccount as String: "mcp-local",
        ]
        var lookup = query
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var found: CFTypeRef?
        let status = SecItemCopyMatching(lookup as CFDictionary, &found)
        if status == errSecSuccess, let data = found as? Data,
           let token = String(data: data, encoding: .utf8) { return token }
        guard status == errSecItemNotFound else {
            throw DesktopError.message("Could not read the OpenArtifact credential from Keychain (\(status)).")
        }
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            throw DesktopError.message("Could not generate a private credential.")
        }
        let token = bytes.map { String(format: "%02x", $0) }.joined()
        var entry = query
        entry[kSecValueData as String] = Data(token.utf8)
        entry[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let saved = SecItemAdd(entry as CFDictionary, nil)
        guard saved == errSecSuccess else {
            throw DesktopError.message("Could not save the OpenArtifact credential in Keychain (\(saved)).")
        }
        return token
    }
}
