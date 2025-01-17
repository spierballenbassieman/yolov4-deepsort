# vim: expandtab:ts=4:sw=4


class TrackState:
    """
    Enumeration type for the single target track state. Newly created tracks are
    classified as `tentative` until enough evidence has been collected. Then,
    the track state is changed to `confirmed`. Tracks that are no longer alive
    are classified as `deleted` to mark them for removal from the set of active
    tracks.

    """

    Tentative = 1
    Confirmed = 2
    Deleted = 3


class Track:
    """
    A single target track with state space `(x, y, a, h)` and associated
    velocities, where `(x, y)` is the center of the bounding box, `a` is the
    aspect ratio and `h` is the height.

    Parameters
    ----------
    mean : ndarray
        Mean vector of the initial state distribution.
    covariance : ndarray
        Covariance matrix of the initial state distribution.
    track_id : int
        A unique track identifier.
    n_init : int
        Number of consecutive detections before the track is confirmed. The
        track state is set to `Deleted` if a miss occurs within the first
        `n_init` frames.
    max_age : int
        The maximum number of consecutive misses before the track state is
        set to `Deleted`.
    feature : Optional[ndarray]
        Feature vector of the detection this track originates from. If not None,
        this feature is added to the `features` cache.

    Attributes
    ----------
    mean : ndarray
        Mean vector of the initial state distribution.
    covariance : ndarray
        Covariance matrix of the initial state distribution.
    track_id : int
        A unique track identifier.
    hits : int
        Total number of measurement updates.
    age : int
        Total number of frames since first occurance.
    time_since_update : int
        Total number of frames since last measurement update.
    state : TrackState
        The current track state.
    features : List[ndarray]
        A cache of features. On each measurement update, the associated feature
        vector is added to this list.

    """

    def __init__(self, mean, covariance, track_id, n_init, max_age,
                 feature=None, class_name=None, color=None):

        self.mean = mean
        self.covariance = covariance
        self.track_id = track_id
        self.hits = 1
        self.age = 1
        self.time_since_update = 0

        self.state = TrackState.Tentative
        self.features = []
        if feature is not None:
            self.features.append(feature)

        self._n_init = n_init
        self._max_age = max_age
        self.class_name = class_name
        self.colors = []
        if color is not None:
            self.colors.append(color)

        # Added by Bas:
        self.color_confirmed = False
        self.confirmed_color = None


    def to_tlwh(self):
        """Get current position in bounding box format `(top left x, top left y,
        width, height)`.

        Returns
        -------
        ndarray
            The bounding box.

        """
        ret = self.mean[:4].copy()
        ret[2] *= ret[3]
        ret[:2] -= ret[2:] / 2
        return ret

    def to_tlbr(self):
        """Get current position in bounding box format `(min x, miny, max x,
        max y)`.

        Returns
        -------
        ndarray
            The bounding box.

        """
        ret = self.to_tlwh()
        ret[2:] = ret[:2] + ret[2:]
        return ret
    
    def get_class(self):
        return self.class_name

    def get_color(self):
        """Return color that has been detected most often for this track"""
        
        # if-statement added by Bas
        if self.color_confirmed:
            return self.confirmed_color # to avoid the color count at every step

        if self.colors:
            return max(set(self.colors), key=self.colors.count)
            
        else:
            return None
   
        
    
    def predict(self, kf):
        """Propagate the state distribution to the current time step using a
        Kalman filter prediction step.

        Parameters
        ----------
        kf : kalman_filter.KalmanFilter
            The Kalman filter.

        """


        self.mean, self.covariance = kf.predict(self.mean, self.covariance)
        self.age += 1
        self.time_since_update += 1
        
        self.last_mean = self.mean
        self.last_covariance = self.covariance

        # if-block added by Bas
    	# if the prediction bbox hits the top of the screen, delete track (otherwise very unpredictably behaviour, bboxes appear at random locations on the screen).
        # Possibly want something similar for bottom of the screen
        # of misschien is dit op een andere manier op te lossen.

        # self.to_tlbr in bbox format `(min x, min y, max x, max y)`
        # if min y is kleiner dan 40.0:
        if self.to_tlbr()[1] < 40.0 or self.to_tlbr()[0] > 1918: 

            self.state = TrackState.Deleted
            return
        
        # Added by Bas. To avoid very large expanding bboxes.  Possibly combine with previous if-statement.
        # Zie ook de if-statements mbt bboxes in object_tracker.py. Maybe want to combine some of it?
        elif self.to_tlwh()[3] > 170:

            self.state = TrackState.Deleted
            return


    def update(self, kf, detection):
        """Perform Kalman filter measurement update step and update the feature
        cache.

        Parameters
        ----------
        kf : kalman_filter.KalmanFilter
            The Kalman filter.
        detection : Detection
            The associated detection.

        """
        
        self.mean, self.covariance = kf.update(
                self.mean, self.covariance, detection.to_xyah())   


        self.features.append(detection.feature)
        

        if detection.color is not None:
                if len(self.colors) < 300:
                    self.colors.append(detection.color)
                else:
                    del self.colors[0]
                    self.colors.append(detection.color)
                    
                ## Added this, to avoid the looping in the get_color function every time
                if not self.color_confirmed and len(self.colors) > 16:
                    self.confirmed_color = self.get_color()
                    self.color_confirmed = True

        ## this block added by Bas. 
        # Comment out if you want to use the other method described in linear_assignment.py.
        # Deze code is de reden dat er soms een prediction als een detection gerendered wordt.
        if self.color_confirmed and (self.confirmed_color != self.colors[-1]): 
            self.colors.pop()
            self.mean = self.last_mean
            self.covariance = self.last_covariance

            self.hits -= 1 

            return


        self.time_since_update = 0
        self.hits += 1
                
        if self.state == TrackState.Tentative and self.hits >= self._n_init:
                    self.state = TrackState.Confirmed

        
    def mark_missed(self):
        """Mark this track as missed (no association at the current time step).
        """
        if self.state == TrackState.Tentative:
            self.state = TrackState.Deleted
        elif self.time_since_update > self._max_age:
            self.state = TrackState.Deleted

    def is_tentative(self):
        """Returns True if this track is tentative (unconfirmed).
        """
        return self.state == TrackState.Tentative

    def is_confirmed(self):
        """Returns True if this track is confirmed."""
        return self.state == TrackState.Confirmed

    def is_deleted(self):
        """Returns True if this track is dead and should be deleted."""
        return self.state == TrackState.Deleted
