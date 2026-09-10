/**
 * Page Object Model for the main chat page (/app).
 *
 * Encapsulates locators and interactions shared across chat specs so that
 * individual tests remain declarative.
 */

import { type Page, type Locator, expect } from "@playwright/test";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";
import { InputBar } from "@tests/e2e/chat/InputBar";

export class ChatPage {
  readonly page: Page;
  readonly inputBar: InputBar;

  // Layout containers
  readonly container: Locator;
  readonly scrollContainer: Locator;

  // Message collections
  readonly humanMessages: Locator;
  readonly aiMessages: Locator;
  readonly usageLimitBanner: Locator;

  // Branching
  readonly branchOrigin: Locator;
  readonly branchOriginLink: Locator;
  readonly branchToast: Locator;
  readonly sidebarBranchEntry: Locator;
  readonly sidebarUnnamedChats: Locator;
  readonly modelPanels: Locator;
  readonly preferredPanelLabel: Locator;
  readonly addModelButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.inputBar = new InputBar(page);
    this.container = page.locator("[data-main-container]");
    this.scrollContainer = page.getByTestId("chat-scroll-container");
    this.humanMessages = page.locator("#onyx-human-message");
    this.aiMessages = page.getByTestId("onyx-ai-message");
    this.usageLimitBanner = page.getByText(/you've reached the usage budget/i);
    this.branchOrigin = page.getByTestId("ChatUI/branch-origin");
    this.branchOriginLink = page.getByTestId("ChatUI/branch-origin-link");
    this.branchToast = page.getByText("New chat created from this message.");
    this.sidebarBranchEntry = page
      .getByTestId("ChatButton")
      .filter({ hasText: /Branch of / })
      .first();
    // A pending sidebar entry has no name and renders as "New Chat".
    this.sidebarUnnamedChats = page
      .getByTestId("ChatButton")
      .filter({ has: page.getByText("New Chat", { exact: true }) });
    this.modelPanels = page.getByTestId("MultiModelPanel");
    this.preferredPanelLabel = page.getByTestId(
      "MultiModelPanel/preferred-label",
    );
    this.addModelButton = page
      .getByTestId("model-selector")
      .getByRole("button", { name: "Add Model" });
  }

  humanMessage(index = 0): Locator {
    return this.humanMessages.nth(index);
  }

  aiMessage(index = 0): Locator {
    return this.aiMessages.nth(index);
  }

  async goto(): Promise<void> {
    await this.page.goto("/app");
    await this.page.waitForLoadState("networkidle");
    await this.inputBar.textbox.waitFor({ state: "visible", timeout: 15000 });
  }

  async scrollTo(position: "top" | "bottom"): Promise<void> {
    await this.scrollContainer.evaluate(async (el, pos) => {
      el.scrollTo({ top: pos === "top" ? 0 : el.scrollHeight });
      await new Promise<void>((r) => requestAnimationFrame(() => r()));
    }, position);
  }

  async screenshotContainer(name: string): Promise<void> {
    await expect(this.container).toBeVisible();
    if ((await this.scrollContainer.count()) > 0) {
      await this.scrollTo("bottom");
    }
    await expectElementScreenshot(this.container, { name });
  }

  /**
   * Captures two screenshots of the chat container for long-content tests:
   * one scrolled to the top and one scrolled to the bottom. Ensures
   * consistent scroll positions regardless of whether the page was just
   * navigated to (top) or just finished streaming (bottom).
   */
  async screenshotContainerTopAndBottom(name: string): Promise<void> {
    await expect(this.container).toBeVisible();

    await this.scrollTo("top");
    await expectElementScreenshot(this.container, { name: `${name}-top` });

    await this.scrollTo("bottom");
    await expectElementScreenshot(this.container, { name: `${name}-bottom` });
  }

  // ---------------------------------------------------------------------------
  // Message assertions
  // ---------------------------------------------------------------------------

  async expectHumanMessage(text: string, index = 0): Promise<void> {
    await expect(this.humanMessage(index)).toContainText(text);
  }

  async expectNoHumanMessages(): Promise<void> {
    await expect(this.humanMessages).toHaveCount(0);
  }

  async expectMessageCounts(human: number, ai: number): Promise<void> {
    await expect(this.humanMessages).toHaveCount(human);
    await expect(this.aiMessages).toHaveCount(ai);
  }

  // ---------------------------------------------------------------------------
  // Branching
  // ---------------------------------------------------------------------------

  /** The `chatId` search param of the page the test is on right now. */
  currentChatId(): string | null {
    return new URL(this.page.url()).searchParams.get("chatId");
  }

  async expectChatId(chatId: string | null): Promise<void> {
    await expect(this.page).toHaveURL(
      new RegExp(`chatId=${chatId ?? ""}(&|$)`),
    );
  }

  async expectChatIdToChangeFrom(chatId: string | null): Promise<void> {
    await this.page.waitForURL(
      (url) => {
        const current = url.searchParams.get("chatId");
        return current !== null && current !== chatId;
      },
      { timeout: 15000 },
    );
  }

  async branchFromAiMessage(index = 0): Promise<void> {
    const message = this.aiMessage(index);
    await message.hover();
    await message.getByTestId("AgentMessage/branch-button").click();
  }

  async branchFromHumanMessage(index = 0): Promise<void> {
    const message = this.humanMessage(index);
    await message.hover();
    await message.getByTestId("HumanMessage/branch-button").click();
  }

  async expectBranchToast(): Promise<void> {
    await expect(this.branchToast).toBeVisible({ timeout: 10000 });
  }

  async expectBranchOrigin(): Promise<void> {
    await expect(this.branchOrigin).toBeVisible({ timeout: 15000 });
    await expect(this.branchOrigin).toContainText("Branched from");
  }

  async expectSidebarBranchEntry(): Promise<void> {
    await expect(this.sidebarBranchEntry).toBeVisible({ timeout: 15000 });
  }

  async clickViewOriginal(): Promise<void> {
    await this.branchOriginLink.click();
  }

  // Multi-model turns render one panel per model, in model order.
  async selectPreferredPanel(index: number): Promise<void> {
    const panel = this.modelPanels.nth(index);
    await panel.hover();
    await panel
      .getByRole("button", { name: "Select This Response", exact: true })
      .click();
  }

  async expectPreferredPanel(index: number): Promise<void> {
    const label = this.page.getByTestId("MultiModelPanel/preferred-label");
    await expect(label).toHaveCount(1);
    await expect(
      this.modelPanels
        .nth(index)
        .getByTestId("MultiModelPanel/preferred-label"),
    ).toBeVisible();
  }

  async branchFromModelPanel(index: number): Promise<void> {
    const panel = this.modelPanels.nth(index);
    await panel.hover();
    await panel.getByTestId("MultiModelPanel/branch-button").click();
  }

  async deselectPreferredPanel(): Promise<void> {
    await this.page.getByTestId("MultiModelPanel/deselect-button").click();
    await expect(this.preferredPanelLabel).toHaveCount(0);
  }

  /** Adds the next available model to the input bar's multi-model selector. */
  async addModelToInputBar(): Promise<void> {
    await this.addModelButton.click();
    const dialog = this.page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 10000 });
    // Only the group holding the current model is expanded by default; open
    // the others so a model from a second provider is reachable.
    const closedGroups = dialog.locator('[aria-expanded="false"]');
    for (let i = (await closedGroups.count()) - 1; i >= 0; i--) {
      await closedGroups.nth(i).click();
    }
    await dialog.locator('[data-interactive-state="empty"]').first().click();
    await this.page.keyboard.press("Escape").catch(() => {});
    await expect(dialog).toBeHidden({ timeout: 5000 });
  }

  /** Sends a message and waits for `responseCount` new assistant messages
   * (one per model in a multi-model turn) and for the chat to get an id. */
  async sendAndWaitForResponses(
    message: string,
    responseCount: number,
  ): Promise<void> {
    const existing = await this.aiMessages.count();
    await this.inputBar.fill(message);
    await this.inputBar.send();
    await expect(this.aiMessages).toHaveCount(existing + responseCount, {
      timeout: 60000,
    });
    await this.page.waitForURL(/chatId=/, { timeout: 10000 });
  }

  async expectNoUnnamedSidebarChat(): Promise<void> {
    await expect(this.sidebarUnnamedChats).toHaveCount(0);
  }

  async sendUntilUsageLimit(maxTurns: number): Promise<void> {
    for (
      let turn = 0;
      turn < maxTurns && !(await this.usageLimitBanner.isVisible());
      turn++
    ) {
      await this.inputBar.fill(`write a few sentences about topic ${turn}`);
      await this.inputBar.send();
      await Promise.race([
        this.usageLimitBanner
          .waitFor({ state: "visible", timeout: 45_000 })
          .catch(() => {}),
        this.aiMessage(turn)
          .waitFor({ state: "visible", timeout: 45_000 })
          .catch(() => {}),
      ]);
    }
  }

  async expectAccountUsageLimit(): Promise<void> {
    await expect(this.usageLimitBanner).toBeVisible();
    await expect(this.page.getByText(/your account/i)).toBeVisible();
  }
}
