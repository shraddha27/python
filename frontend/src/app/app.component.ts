import { Component, OnInit, inject } from "@angular/core";
import { Router, RouterModule } from "@angular/router";
import { CommonModule } from "@angular/common";
import { AuthStore } from "./store/auth.signal-store";
import { AppService } from "./app.service";
import { CsrfService } from "./csrf.service";

@Component({
  selector: "app-root",
  templateUrl: "./app.component.html",
  styleUrls: ["./app.component.css"],
  standalone: false,
})
export class AppComponent implements OnInit {
  title = "Task Manager";
  authStore = inject(AuthStore) as any;
  private readonly appService = inject(AppService);
  private readonly router = inject(Router);
  private readonly csrfService = inject(CsrfService);

  ngOnInit(): void {
    // Initialize CSRF token
    this.csrfService.getToken().subscribe();

    // Initialize auth state from localStorage
    this.authStore.initializeFromStorage();

    // Refresh auth state from the HttpOnly cookie-backed session.
    this.authStore.getCurrentUser(this.appService);
  }

  logout(): void {
    this.authStore.logout(this.appService, this.router);
  }
}
