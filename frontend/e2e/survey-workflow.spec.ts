import { test, expect } from "@playwright/test";

test("upload, review, chart, dashboard and anonymous sharing", async ({
  page,
  browser,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/login");
  await page
    .getByLabel("Username or email")
    .fill(process.env.E2E_EMAIL || "ci@example.org");
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.E2E_PASSWORD || "ci-password-67890");
  await page.locator("form").getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
  await page.goto("/datasets");
  await page.getByRole("button", { name: "Upload data", exact: true }).click();
  const name = `Browser survey ${Date.now()}`;
  const rows = Array.from(
    { length: 60 },
    (_, i) =>
      `${i + 1},${i % 2 ? "Female" : "Male"},${100 + i * 3},${1 + i / 100}`,
  );
  await page
    .locator('input[type="file"]')
    .setInputFiles({
      name: `${name}.csv`,
      mimeType: "text/csv",
      buffer: Buffer.from("id,sex,income,weight\n" + rows.join("\n")),
    });
  await page.getByRole("button", { name: "Upload and review" }).click();
  const review = page.getByRole("dialog", { name: "Review import changes" });
  await expect(review).toBeVisible({ timeout: 60_000 });
  await expect(review).toContainText("60");
  const accepted = page.waitForResponse(
    (r) =>
      r.url().includes("/reviews/") &&
      r.url().endsWith("/accept") &&
      r.request().method() === "POST",
  );
  await review.getByRole("button", { name: "Accept import" }).click();
  const result = await (await accepted).json();
  expect(result.datasets).toHaveLength(1);
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page.goto(`/explore?dataset=${result.datasets[0].id}`);
  await page.getByRole("button", { name: "Run query", exact: true }).click();
  await page
    .getByRole("button", { name: "Save as chart", exact: true })
    .click();
  const chartName = `Interviews ${Date.now()}`;
  const save = page.getByRole("dialog", { name: "Save as chart" });
  await save.locator("input").fill(chartName);
  await save.getByRole("button", { name: "Save chart", exact: true }).click();
  await expect(save).not.toBeVisible();

  // The UI must not offer a survey weight that the selected statistic ignores.
  await page.getByLabel("Aggregation", { exact: true }).selectOption("median");
  // Numbered, because a summary can carry several measures and each picker's
  // label is also the id its option list is addressed by.
  await expect(page.getByLabel("Measure 1 survey weight")).toBeDisabled();

  await page.goto("/dashboards");
  await page
    .getByRole("button", { name: "New dashboard", exact: true })
    .click();
  const boardName = `Fieldwork ${Date.now()}`;
  const create = page.getByRole("dialog", { name: "New dashboard" });
  await create.getByPlaceholder("Daily field monitoring").fill(boardName);
  await create.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("link", { name: boardName, exact: true }).click();
  await page
    .getByRole("button", { name: "Add widget", exact: true })
    .first()
    .click();
  const widget = page.getByRole("dialog", { name: /Add.*widget/i });
  await widget
    .locator("select")
    .nth(1)
    .selectOption({ label: `${chartName} (bar)` });
  await widget.getByRole("button", { name: "Add widget", exact: true }).click();
  await expect(widget).not.toBeVisible();
  await expect(page.getByText(chartName, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Share", exact: true }).click();
  await page.getByPlaceholder("Field supervisors").fill("Public test");
  const shared = page.waitForResponse(
    (r) => r.url().endsWith("/share-links") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create link", exact: true }).click();
  const link = await (await shared).json();
  const publicContext = await browser.newContext();
  const publicPage = await publicContext.newPage();
  publicPage.on("pageerror", (error) => errors.push(error.message));
  await publicPage.goto(new URL(`/shared/${link.token}`, page.url()).href);
  await expect(publicPage.getByText(chartName, { exact: true })).toBeVisible();
  await expect(
    publicPage.getByRole("button", { name: "Add widget", exact: true }),
  ).toHaveCount(0);
  await publicContext.close();
  expect(errors).toEqual([]);
});
