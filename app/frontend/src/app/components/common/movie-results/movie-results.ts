import { Component, DestroyRef, inject, input, OnInit, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize } from 'rxjs';
import { WatchlistService } from '../../../shared/services/backend/watchlist/watchlist.service';
import { authError } from '../../../shared/services/backend/auth/auth.service';

export interface Movie {
  id: string; title: string; original_title?: string | null; synopsis: string | null; poster_url: string | null;
  release_date: string | null; duration_minutes: number | null; genres: string[] | null;
  actors: string[] | null; directors: string[] | null; languages?: string[] | null;
  countries?: string[] | null; movie_type?: string | null;
}

@Component({
  selector: 'app-movie-results',
  imports: [DatePipe],
  templateUrl: './movie-results.html',
  styleUrls: ['../../../shared/styles/movie-list.scss', './movie-results.scss'],
})
export class MovieResults implements OnInit {
  readonly movies = input.required<Movie[]>();
  readonly notes = input<Record<string, string>>({});
  readonly watchlist = inject(WatchlistService);
  private readonly destroyRef = inject(DestroyRef);
  readonly selected = signal<Movie | null>(null);
  readonly pending = signal(false);
  readonly error = signal('');
  readonly failedPosters = signal<Set<string>>(new Set());
  private trigger: HTMLButtonElement | null = null;

  ngOnInit(): void {
    this.watchlist.reset();
    this.watchlist.load();
    this.destroyRef.onDestroy(() => this.watchlist.reset());
  }

  open(movie: Movie, dialog: HTMLDialogElement, trigger: HTMLButtonElement): void {
    this.selected.set(movie); this.trigger = trigger; this.error.set('');
    this.watchlist.load();
    dialog.showModal();
  }
  close(): void {
    this.selected.set(null);
    if (this.trigger?.isConnected) this.trigger.focus();
  }
  backdrop(event: MouseEvent, dialog: HTMLDialogElement): void {
    const box = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
  }
  save(movie: Movie, action: 'list' | 'watched', dialog: HTMLDialogElement): void {
    if (this.pending() || !this.watchlist.loaded()) return;
    const inList = this.watchlist.ids().includes(movie.id);
    const watched = this.watchlist.watchedIds().includes(movie.id);
    if (action === 'list' && watched) return;
    this.pending.set(true); this.error.set('');
    const request = action === 'list' ? this.watchlist.update(movie.id, !inList)
      : watched ? this.watchlist.markUnwatched(movie.id) : this.watchlist.markWatched(movie.id);
    request.pipe(takeUntilDestroyed(this.destroyRef), finalize(() => this.pending.set(false))).subscribe({
      next: () => { if (this.selected()?.id === movie.id) dialog.close(); },
      error: error => {
        if (this.selected()?.id === movie.id) this.error.set(authError(error));
        this.watchlist.load();
      },
    });
  }
  posterFailed(id: string): void { this.failedPosters.update(ids => new Set([...ids, id])); }
}
