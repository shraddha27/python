import { HttpClientModule, HTTP_INTERCEPTORS } from "@angular/common/http";
import { APP_INITIALIZER, NgModule } from "@angular/core";
import { BrowserModule } from "@angular/platform-browser";
import { FormsModule } from "@angular/forms";
import { RouterModule, Routes } from "@angular/router";

import { AppComponent } from "./app.component";
import { TaskListComponent } from "./task-list/task-list.component";
import { HttpErrorInterceptor } from "./http-error.interceptor";
import { LoginComponent } from "./login/login.component";
import { AuthInterceptor } from "./auth.interceptor";
import { AuthGuard } from "./auth.guard";
import { AiChatComponent } from "./ai-chat/ai-chat.component";
import { VectorSearchComponent } from "./vector-search/vector-search.component";
import { AiIndexingComponent } from "./ai-indexing/ai-indexing.component";
import { AgentsComponent } from "./agents/agents.component";
import { LangGraphWorkflowComponent } from "./langraph-workflow/langraph-workflow.component";
import { AuthStore } from "./store/auth.signal-store";

export function initializeAuth(authStore: AuthStore): () => void {
  return () => authStore.initializeFromStorage();
}

const routes: Routes = [
  { path: "login", component: LoginComponent },
  { path: "tasks", component: TaskListComponent, canActivate: [AuthGuard] },
  { path: "ai/chat", component: AiChatComponent, canActivate: [AuthGuard] },
  {
    path: "ai/search",
    component: VectorSearchComponent,
    canActivate: [AuthGuard],
  },
  {
    path: "ai/index",
    component: AiIndexingComponent,
    canActivate: [AuthGuard],
  },
  { path: "ai/agents", component: AgentsComponent, canActivate: [AuthGuard] },
  { path: "ai/workflow", component: LangGraphWorkflowComponent, canActivate: [AuthGuard] },
  { path: "", redirectTo: "tasks", pathMatch: "full" },
  { path: "**", redirectTo: "tasks" },
];

@NgModule({
  declarations: [AppComponent, TaskListComponent, LoginComponent],
  imports: [
    BrowserModule,
    HttpClientModule,
    FormsModule,
    RouterModule.forRoot(routes),
    AiChatComponent,
    VectorSearchComponent,
    AiIndexingComponent,
    AgentsComponent,
    LangGraphWorkflowComponent,
  ],
  providers: [
    {
      provide: APP_INITIALIZER,
      useFactory: initializeAuth,
      deps: [AuthStore],
      multi: true,
    },
    {
      provide: HTTP_INTERCEPTORS,
      useClass: HttpErrorInterceptor,
      multi: true,
    },
    {
      provide: HTTP_INTERCEPTORS,
      useClass: AuthInterceptor,
      multi: true,
    },
  ],
  bootstrap: [AppComponent],
})
export class AppModule {}
