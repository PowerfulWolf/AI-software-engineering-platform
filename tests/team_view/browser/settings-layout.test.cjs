const { test } = require("node:test");
const assert = require("node:assert/strict");
const { ui } = require("./fixture.cjs");

test("Basic settings separates modules and keeps retry content compact at desktop and mobile widths", async (t) => {
  const h = await ui(t);
  await h.page.locator("#nav-settings").click();
  await h.page.locator("#content .settings-form").waitFor();
  for (const width of [1440, 768, 390]) {
    await h.page.setViewportSize({width, height: 1000});
    const layout = await h.page.locator(".settings-form").evaluate(form => {
      const heading = Array.from(form.querySelectorAll("h3")).find(node => /重试/.test(node.textContent));
      const description = heading.nextElementSibling;
      const fields = description.nextElementSibling;
      const sections = Array.from(form.querySelectorAll(".settings-section"));
      return {
        headingGap: description.getBoundingClientRect().top - heading.getBoundingClientRect().bottom,
        fieldsGap: fields.getBoundingClientRect().top - description.getBoundingClientRect().bottom,
        sections: sections.map(section => ({
          border: parseFloat(getComputedStyle(section).borderTopWidth),
          style: getComputedStyle(section).borderTopStyle,
        })),
        overflow: document.documentElement.scrollWidth > window.innerWidth,
      };
    });
    assert.ok(layout.headingGap >= 0 && layout.headingGap <= 12,
      `${width}px: heading/description gap must be compact, got ${layout.headingGap}`);
    assert.ok(layout.fieldsGap >= 0 && layout.fieldsGap <= 20,
      `${width}px: description/fields gap must be compact, got ${layout.fieldsGap}`);
    assert.equal(layout.sections.length, 3, "platform/team, runtime and retry are named modules");
    assert.ok(layout.sections.every(section => section.border >= 1 && section.style === "solid"),
      "each module has a visible divider, including the metadata boundary");
    assert.equal(layout.overflow, false, `${width}px: no horizontal overflow`);
  }
});
