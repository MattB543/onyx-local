import { test, expect } from "@playwright/test";
import { loginAs, loginAsRandomUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const FIRST_QUESTION = "What is 2+2? Answer in one sentence.";
const SECOND_QUESTION = "What is 3+3? Answer in one sentence.";

test.describe("Branch from message", () => {
  let chatPage: ChatPage;

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAsRandomUser(page);
    chatPage = new ChatPage(page);
    await chatPage.goto();
  });

  test("branching at an assistant message copies the history up to it", async ({
    page,
  }) => {
    await sendMessage(page, FIRST_QUESTION);
    await sendMessage(page, SECOND_QUESTION);
    const originalChatId = chatPage.currentChatId();

    await chatPage.branchFromAiMessage(0);

    await chatPage.expectChatIdToChangeFrom(originalChatId);
    await chatPage.expectBranchToast();
    await chatPage.expectMessageCounts(1, 1);
    await chatPage.expectHumanMessage(FIRST_QUESTION);
    await chatPage.expectBranchOrigin();
    await chatPage.expectSidebarBranchEntry();

    await chatPage.clickViewOriginal();
    await chatPage.expectChatId(originalChatId);
    await chatPage.expectMessageCounts(2, 2);
  });

  test("branching at a user message prefills the input with that message", async ({
    page,
  }) => {
    await sendMessage(page, FIRST_QUESTION);
    await sendMessage(page, SECOND_QUESTION);
    const originalChatId = chatPage.currentChatId();

    await chatPage.branchFromHumanMessage(1);

    await chatPage.expectChatIdToChangeFrom(originalChatId);
    await chatPage.expectMessageCounts(1, 1);
    await chatPage.inputBar.expectText(SECOND_QUESTION);

    await chatPage.inputBar.send();
    await expect(chatPage.aiMessages).toHaveCount(2, { timeout: 30000 });
    await chatPage.expectMessageCounts(2, 2);
    await chatPage.expectHumanMessage(SECOND_QUESTION, 1);
  });

  test("branching at the first user message gives an empty chat with the question prefilled", async ({
    page,
  }) => {
    await sendMessage(page, FIRST_QUESTION);
    const originalChatId = chatPage.currentChatId();

    await chatPage.branchFromHumanMessage(0);

    await chatPage.expectChatIdToChangeFrom(originalChatId);
    await chatPage.expectNoHumanMessages();
    await expect(chatPage.aiMessages).toHaveCount(0);
    await chatPage.expectBranchOrigin();
    await chatPage.inputBar.expectText(FIRST_QUESTION);
  });

  test("two branches with the same prefilled question both prefill it", async ({
    page,
  }) => {
    await sendMessage(page, FIRST_QUESTION);
    const originalChatId = chatPage.currentChatId();

    await chatPage.branchFromHumanMessage(0);
    await chatPage.expectChatIdToChangeFrom(originalChatId);
    await chatPage.inputBar.expectText(FIRST_QUESTION);

    await chatPage.clickViewOriginal();
    await chatPage.expectChatId(originalChatId);
    await chatPage.inputBar.expectEmpty();

    await chatPage.branchFromHumanMessage(0);
    await chatPage.expectChatIdToChangeFrom(originalChatId);
    await chatPage.inputBar.expectText(FIRST_QUESTION);
  });
});

test.describe("Branch from a project chat", () => {
  const PROJECT_NAME = `PW Branch Project ${Date.now()}`;
  let projectId: number | null = null;

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAsRandomUser(page);
    projectId = await new OnyxApiClient(page.request).createProject(
      PROJECT_NAME
    );
  });

  test.afterEach(async ({ page }) => {
    if (projectId === null) return;
    await new OnyxApiClient(page.request).deleteProject(projectId);
    projectId = null;
  });

  test("the branch lands in the same project without a stray Recents entry", async ({
    page,
  }) => {
    const chatPage = new ChatPage(page);
    await page.goto(`/app?projectId=${projectId}`);
    await chatPage.inputBar.textbox.waitFor({ state: "visible" });
    await sendMessage(page, FIRST_QUESTION);
    const originalChatId = chatPage.currentChatId();

    await chatPage.branchFromAiMessage(0);

    await chatPage.expectChatIdToChangeFrom(originalChatId);
    await chatPage.expectBranchToast();
    await chatPage.expectMessageCounts(1, 1);
    // Recents excludes project chats, so the only place a "Branch of" row can
    // render is under the project folder.
    await chatPage.expectSidebarBranchEntry();
    await chatPage.expectNoUnnamedSidebarChat();
  });
});

// A second public provider gives the model selector a second option, which is
// what a multi-model turn needs. It is removed again after the test.
test.describe("Branch from a multi-model turn", () => {
  let providerId: number | null = null;

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const client = new OnyxApiClient(page.request);
    providerId = await client.createProvider(
      `PW Branch Provider ${Date.now()}`
    );
  });

  test.afterEach(async ({ page }) => {
    if (providerId === null) return;
    const client = new OnyxApiClient(page.request);
    await client.deleteProvider(providerId, { force: true });
    providerId = null;
  });

  test("a non-preferred model card can be branched from either side without changing the source's preference", async ({
    page,
  }) => {
    const chatPage = new ChatPage(page);
    await chatPage.goto();
    await chatPage.addModelToInputBar();
    await chatPage.sendAndWaitForResponses(FIRST_QUESTION, 2);
    await expect(chatPage.modelPanels).toHaveCount(2);
    const originalChatId = chatPage.currentChatId();

    // Preferred on the left, branch from the card to its right.
    await chatPage.selectPreferredPanel(0);
    await chatPage.expectPreferredPanel(0);
    await chatPage.branchFromModelPanel(1);

    await chatPage.expectChatIdToChangeFrom(originalChatId);
    await chatPage.expectBranchToast();
    await chatPage.expectMessageCounts(1, 1);
    await expect(chatPage.modelPanels).toHaveCount(0);

    await chatPage.clickViewOriginal();
    await chatPage.expectChatId(originalChatId);
    await expect(chatPage.modelPanels).toHaveCount(2);
    await chatPage.expectPreferredPanel(0);

    // Preferred on the right, branch from the card to its left.
    await chatPage.deselectPreferredPanel();
    await chatPage.selectPreferredPanel(1);
    await chatPage.expectPreferredPanel(1);
    await chatPage.branchFromModelPanel(0);

    await chatPage.expectChatIdToChangeFrom(originalChatId);
    await chatPage.expectMessageCounts(1, 1);

    await chatPage.clickViewOriginal();
    await chatPage.expectChatId(originalChatId);
    await chatPage.expectPreferredPanel(1);
  });
});
