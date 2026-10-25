import Foundation

// A read-only protocol check: initialize, acknowledge, list tools, close the session.
// Credentials are supplied by native code and never passed to the web view.
enum MCPClient {
    static func check(url: URL, token: String) async throws -> Int {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 15
        let client = URLSession(configuration: configuration)
        defer { client.invalidateAndCancel() }
        var headers = ["Authorization": "Bearer \(token)", "Accept": "application/json, text/event-stream",
                       "Content-Type": "application/json"]
        func send(_ body: [String: Any], headers: [String: String]) async throws -> (Data, HTTPURLResponse) {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.allHTTPHeaderFields = headers
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            let (data, response) = try await client.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                throw DesktopError.message("MCP authentication or request failed (HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)).")
            }
            return (data, http)
        }
        let (initialized, response) = try await send([
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": ["protocolVersion": "2025-03-26", "capabilities": [:],
                       "clientInfo": ["name": "openartifact-desktop", "version": "0.2.0"]],
        ], headers: headers)
        let result = try message(initialized, id: 1)
        if let session = response.value(forHTTPHeaderField: "Mcp-Session-Id") {
            headers["Mcp-Session-Id"] = session
        }
        if let version = result["protocolVersion"] as? String { headers["MCP-Protocol-Version"] = version }
        do {
            _ = try await send(["jsonrpc": "2.0", "method": "notifications/initialized"], headers: headers)
            let (data, _) = try await send(["jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": [:]], headers: headers)
            let tools = try message(data, id: 2)["tools"] as? [[String: Any]]
            guard let tools = tools, !tools.isEmpty else { throw DesktopError.message("MCP returned no tools.") }
            await close(client, url: url, headers: headers)
            return tools.count
        } catch {
            await close(client, url: url, headers: headers)
            throw error
        }
    }

    private static func close(_ client: URLSession, url: URL, headers: [String: String]) async {
        guard headers["Mcp-Session-Id"] != nil else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        request.allHTTPHeaderFields = headers
        _ = try? await client.data(for: request)
    }

    private static func message(_ data: Data, id: Int) throws -> [String: Any] {
        var candidates = [data]
        if let text = String(data: data, encoding: .utf8) {
            candidates += text.components(separatedBy: "\n").compactMap {
                $0.hasPrefix("data:") ? Data($0.dropFirst(5).trimmingCharacters(in: .whitespaces).utf8) : nil
            }
        }
        for candidate in candidates {
            if let object = (try? JSONSerialization.jsonObject(with: candidate)) as? [String: Any],
               object["id"] as? Int == id, let result = object["result"] as? [String: Any] { return result }
        }
        throw DesktopError.message("The server returned an invalid MCP response.")
    }
}
