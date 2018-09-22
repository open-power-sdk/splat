#include<stdio.h>
#include<string.h>
#include<pthread.h>
#include<stdlib.h>
#include<unistd.h>
 
#define NTHREADS 2
#define NITERS 3
pthread_t 	tid[NTHREADS];
int 		counter;
pthread_mutex_t lock1, lock2;
 

void* critSection(void *arg)
{
    int local_counter;
    pthread_mutex_lock(&lock1);
    counter++;
    local_counter = counter;
    pthread_mutex_unlock(&lock1);

    printf("Job %d has started\n", local_counter);

    int i;
    for (i = 0; i < NITERS; i++) {
	while (pthread_mutex_trylock(&lock2) != 0)
		usleep(100);
 
        sleep(1);

    	pthread_mutex_unlock(&lock2);

    	sleep(1);
    }
    printf("Job %d has finished\n", local_counter);
    return NULL;
}

int main(void)
{
    int error, i = 0;
 
    if (pthread_mutex_init(&lock1, NULL) != 0) { printf("\n mutex init has failed\n"); return 1; }
    if (pthread_mutex_init(&lock2, NULL) != 0) { printf("\n mutex init has failed\n"); return 1; }
 
    while(i < NTHREADS) {
        error = pthread_create( &(tid[i]), NULL, &critSection, NULL );
        printf("Thread id = %lx\n", tid[i]);
        if (error != 0)
            printf("Thread can't be created :[%s]", strerror(error));
        i++;
    }
 
    i = 0;
    while(i < NTHREADS) {
    	pthread_join(tid[i], NULL);
	i++;
    }		

    pthread_mutex_destroy(&lock1);
    pthread_mutex_destroy(&lock2);
    return 0;
}
