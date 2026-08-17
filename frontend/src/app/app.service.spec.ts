import { TestBed } from "@angular/core/testing";
import {
  HttpClientTestingModule,
  HttpTestingController,
} from "@angular/common/http/testing";
import { AppService } from "./app.service";
import { Task } from "./task.model";
import { environment } from "../environments/environment";

describe("AppService", () => {
  let service: AppService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [AppService],
    });
    service = TestBed.inject(AppService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it("should be created", () => {
    expect(service).toBeTruthy();
  });

  it("should get tasks", () => {
    const mockTasks: Task[] = [
      {
        id: 1,
        title: "Task 1",
        description: "Desc 1",
        completed: false,
        created_at: "2023-01-01",
      },
      {
        id: 2,
        title: "Task 2",
        description: "Desc 2",
        completed: true,
        created_at: "2023-01-02",
      },
    ];

    service.getTasks().subscribe((tasks) => {
      expect(tasks).toEqual(mockTasks);
    });

    const req = httpMock.expectOne(`${environment.apiUrl}/tasks/`);
    expect(req.request.method).toBe("GET");
    req.flush(mockTasks);
  });

  it("should add task", () => {
    const newTask = { title: "New Task", description: "New Desc" };
    const mockResponse: Task = {
      id: 3,
      ...newTask,
      completed: false,
      created_at: "2023-01-03",
    };

    service.addTask(newTask).subscribe((task) => {
      expect(task).toEqual(mockResponse);
    });

    const req = httpMock.expectOne(`${environment.apiUrl}/tasks/`);
    expect(req.request.method).toBe("POST");
    expect(req.request.body).toEqual(newTask);
    req.flush(mockResponse);
  });

  it("should update task", () => {
    const task: Task = {
      id: 1,
      title: "Updated Task",
      description: "Updated",
      completed: true,
      created_at: "2023-01-01",
    };

    service.updateTask(task).subscribe((updatedTask) => {
      expect(updatedTask).toEqual(task);
    });

    const req = httpMock.expectOne(`${environment.apiUrl}/tasks/1/`);
    expect(req.request.method).toBe("PUT");
    expect(req.request.body).toEqual(task);
    req.flush(task);
  });
});
