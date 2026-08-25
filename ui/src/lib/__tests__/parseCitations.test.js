import { describe, expect, it } from "vitest";
import { groupCitationsByFile } from "../parseCitations.js";

function citation(file, section) {
  return { file, section, version: "v1", effectiveDate: "2025-11-05" };
}

describe("groupCitationsByFile", () => {
  it("groups clause citations from the same file onto one entry, deduped", () => {
    const citations = [
      citation("L1-POL-10.txt", "Заалт 2.1: Text one"),
      citation("L1-POL-10.txt", "Заалт 3.1: Text two"),
      citation("L1-POL-10.txt", "Заалт 2.1: Text one again"),
    ];

    const groups = groupCitationsByFile(citations);

    expect(groups).toHaveLength(1);
    expect(groups[0].file).toBe("L1-POL-10.txt");
    expect(groups[0].clauseNumbers).toEqual(["2.1", "3.1"]);
  });

  it("numerically sorts clause numbers instead of string-sorting them", () => {
    const citations = [
      citation("L1-POL-18.txt", "Заалт 4.10: Text"),
      citation("L1-POL-18.txt", "Заалт 4.2: Text"),
      citation("L1-POL-18.txt", "Заалт 3.1: Text"),
    ];

    const groups = groupCitationsByFile(citations);

    // A plain string sort would put "4.10" before "4.2"; numeric sort must not.
    expect(groups[0].clauseNumbers).toEqual(["3.1", "4.2", "4.10"]);
  });

  it("renders a file with no clause number as an empty clauseNumbers list", () => {
    const citations = [citation("Чөлөө олгох журам.pdf", "1.2")];

    const groups = groupCitationsByFile(citations);

    expect(groups[0].file).toBe("Чөлөө олгох журам.pdf");
    expect(groups[0].clauseNumbers).toEqual([]);
  });

  it("keeps separate files as separate entries, in first-appearance order", () => {
    const citations = [
      citation("B.txt", "Заалт 1.1: Text"),
      citation("A.txt", "Заалт 2.1: Text"),
      citation("B.txt", "Заалт 1.2: Text"),
    ];

    const groups = groupCitationsByFile(citations);

    expect(groups.map((g) => g.file)).toEqual(["B.txt", "A.txt"]);
    expect(groups[0].clauseNumbers).toEqual(["1.1", "1.2"]);
    expect(groups[1].clauseNumbers).toEqual(["2.1"]);
  });
});
