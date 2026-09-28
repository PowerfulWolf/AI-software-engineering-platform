import XCTest
@testable import SandboxFixture

final class FixtureTests: XCTestCase {
    func testFixtureValue() { XCTAssertEqual(fixtureValue(), 42) }
    func testCandidateSourceIsReadOnly() {
        let url = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
            .appendingPathComponent("forbidden-source-write.txt")
        XCTAssertThrowsError(try Data("must not write".utf8).write(to: url))
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
    }
}
